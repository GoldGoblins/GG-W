"""Small, deterministic GAME ENGINE runtime for the desktop preview.

This is deliberately a playable vertical slice rather than a pretend MMO
server.  The simulation uses fixed steps, bounded pools and a spatial grid;
the QML surface only observes a compact render snapshot.  That keeps the
editor responsive and gives us a measurable foundation for a later native
runtime without importing a large engine or any proprietary game assets.
"""

from __future__ import annotations

import json
import math
import copy
import bisect
import threading
import time
from collections import OrderedDict
from typing import Any

from backend import game_engine_cinematic as cinematic
from backend import game_engine_combat as combat_contract
from backend import game_engine_enchants as enchant_contract
from backend import game_engine_firearms as firearms_contract
from backend import game_engine_content as content_catalog
from backend import game_engine_controller as controller
from backend import game_engine_dialogue as dialogue_contract
from backend import game_engine_dos as dos_contract
from backend import game_engine_economy as economy_contract
from backend import game_engine_animation as animation_contract
from backend import game_engine_addons as addons_contract
from backend import game_engine_assets as assets_contract
from backend import game_engine_character_creation as character_creation
from backend import game_engine_editor as editor_contract
from backend import game_engine_events as events_contract
from backend import game_engine_factions as factions_contract
from backend import game_engine_fallback as fallback_contract
from backend import game_engine_gear as gear_contract
from backend import game_engine_input as input_contract
from backend import game_engine_items as item_state
from backend import game_engine_fauna as fauna_contract
from backend import game_engine_ecology as ecology_contract
from backend import game_engine_nature as nature_contract
from backend import game_engine_nature_catalog as nature_catalog
from backend import game_engine_actions as actions_contract
from backend import game_engine_life as life_contract
from backend import game_engine_mobility as mobility_contract
from backend import game_engine_mmo as mmo
from backend import game_engine_nav as nav_contract
from backend import game_engine_npc as npc_contract
from backend import game_engine_npc_identity as identity_contract
from backend import game_engine_npc_progression as npc_progression
from backend import game_engine_physics as physics
from backend import game_engine_progression as progression
from backend import game_engine_quests as quests_contract
from backend import game_engine_render as render_contract
from backend import game_engine_schedules as schedules_contract
from backend import game_engine_social as social_contract
from backend import game_engine_settlement as settlement_contract
from backend import game_engine_terrain as terrain_contract
from backend import game_engine_planet as planet_contract
from backend import game_engine_trade as trade_contract
from backend import game_engine_world as world
from backend import game_engine_world_events as world_events_contract
from backend.game_engine_world_population import WorldPopulation
from backend import game_engine_world_places as world_places_contract
from backend.game_engine_adapter_spells import SpellsMixin
from backend.game_engine_adapter_rides import RidesMixin
from backend.game_engine_adapter_survival import SurvivalMixin
from backend.game_engine_local_custody_services import SharedLocalServicesMixin
from backend.game_engine_rigid_physics import PhysicsScene, RigidPhysicsMixin


SCHEMA = "gg.game-engine.runtime.v1"
FIXED_HZ = 60
FIXED_DT = 1.0 / FIXED_HZ
# Physics stays deterministic at 60 Hz.  The UI consumes a bounded render
# snapshot at a lower cadence so Python/QML marshalling cannot compete with
# the desktop shell's frame budget.  Stress mode deliberately gives the UI a
# little more headroom while leaving the simulation cadence unchanged.
RENDER_UPDATE_HZ = 60
STRESS_RENDER_UPDATE_HZ = 60
# A DOS column frame costs about 10 ms.  Rebuilding it on every 60 Hz render
# tick would hold the simulation lock for most of the frame.  Ten hertz is
# enough for the picture to follow walking and turning, and it keeps the
# fixed step responsive.  The last frame stays on the stream between builds
# so the canvas never falls back to a stale full-status snapshot.
DOS_FRAME_INTERVAL_S = 0.10
MAX_CATCH_UP_STEPS = 4
MAX_ENTITIES = 2048
MAX_PARTICLES = 4096
MAX_CHUNKS = 64
# Gameplay chunks stay bounded for physics/navigation/network interest.  The
# visual stream has its own cap because its outer cells are HLOD-only.
MAX_RENDER_CHUNKS = terrain_contract.MAX_TERRAIN_CELLS
RENDER_ENTITY_LIMIT = 96
RENDER_PARTICLE_LIMIT = 128
STATIC_HEIGHT_CACHE_LIMIT = 2048
MOVING_HEIGHT_CACHE_LIMIT = 2048
MAX_REPLAY_INPUTS = 1800
NPC_WORLD_ACTION_RADIUS_M = 2.25
NPC_WORLD_ACTION_COOLDOWN_S = 4.0
MAX_NPC_WORLD_ACTIONS_PER_PASS = 4
POPULATION_PROMOTION_INTERVAL_S = 12.0
MAX_POPULATION_PROMOTIONS = 4
CHUNK_SIZE = world.CHUNK_SIZE
MOVEMENT_MODES = world.MOVEMENT_MODES
WORLD_SEED = terrain_contract.DEFAULT_WORLD_SEED
AMBIENT_LIFE_SPAWNS = life_contract.DEFAULT_SPAWNS


def _clamp(value: Any, low: float, high: float, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return max(low, min(high, number))


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _cell_coordinate(value: Any) -> int | None:
    """Normalize an explicit authoring coordinate without accepting fractions."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or not number.is_integer():
        return None
    return int(number)


def _round(value: float, places: int = 3) -> float:
    return round(float(value), places)


from backend.game_engine_gameplay import GameplayMixin


from backend.game_engine_adapter_local_actions import LocalActionsMixin
from backend.game_engine_adapter_controls import ClientControlsMixin


from backend.game_engine_adapter_local_client import LocalClientMixin
from backend.game_engine_adapter_services import ServicesMixin

class GameEngineRuntime(RigidPhysicsMixin, SharedLocalServicesMixin, SurvivalMixin, RidesMixin, SpellsMixin, ClientControlsMixin, LocalClientMixin, ServicesMixin, LocalActionsMixin, GameplayMixin):
    """Threaded local simulation with bounded, inspectable state."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._rigid_physics = PhysicsScene(FIXED_HZ)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._running = False
        self._stress = False
        self._recording = False
        self._replaying = False
        self._replay_inputs: list[dict[str, Any]] = []
        self._replay_index = 0
        self._recorded_inputs: list[dict[str, Any]] = []
        self._input = self._default_input()
        # UI settings are session-level state, like WoW keybindings and addon
        # profiles.  World resets and render stress passes must not erase them.
        self._keybindings = input_contract.new_bindings()
        self._addons = addons_contract.new_state()
        self._movement_mode = "GROUND"
        self._vehicle_kind = "NONE"
        self._boat_entity_index: int | None = None
        self._locomotion_distance_m = 0.0
        self._camera_yaw = 0.0
        self._camera_pitch = -8.0
        self._camera_distance = world.DEFAULT_CAMERA_DISTANCE_M
        self._jump_held = False
        self._jump_count = 0
        self._double_jump_pose_remaining_s = 0.0
        self._coyote_time_remaining_s = 0.0
        self._jump_buffer_remaining_s = 0.0
        self._jump_hold_time_s = 0.0
        self._grapple_held = False
        self._grapple_anchor: tuple[float, float, float] | None = None
        self._grapple_rope_length = 0.0
        self._grapple_projectile: dict[str, Any] | None = None
        self._grounded = True
        self._sprinting = False
        self._content = content_catalog.starter_content()
        self._available_content_packs = content_catalog.available_content_packs()
        self._active_content_pack_ids: list[str] = []
        self._set_life_spawns_locked(life_contract.spawns_from_content(self._content))
        self._promoted_life_ids: set[str] = set()
        self._last_population_promotion_s = 0.0
        self._item_catalog = item_state.catalog_from_content(self._content)
        self._gear_tables = gear_contract.tables_from_content(self._content)
        self._people_catalog = identity_contract.catalog_from_content(self._content)
        self._quest_catalog = quests_contract.normalized_catalog(
            self._content.get("quests")
        )
        self._dialogue_catalog = dialogue_contract.normalized_catalog(
            self._content.get("dialogue")
        )
        self._vendor_catalog = economy_contract.catalog_from_content(self._content)
        self._individual_state = identity_contract.runtime_state(self._people_catalog)
        self._faction_state = factions_contract.new_state(self._people_catalog.values())
        self._quest_state = quests_contract.new_state()
        self._quest_visit_presence: set[str] = set()
        self._dialogue_state = dialogue_contract.new_state()
        self._engine_quest_panel={};self._engine_gossip_hidden=False
        self._social_state = social_contract.new_state()
        self._world_event_catalog = world_events_contract.normalized_catalog(
            self._content.get("world_events")
        )
        self._world_event_state = world_events_contract.new_state()
        self._profession_state = copy.deepcopy(
            self._gear_tables.get("professions", {})
        )
        self._inventory: dict[str, int] = {}
        self._loot_items: list[dict[str, Any]] = []
        self._loot_counter = 0
        self._item_instances: dict[str, dict[str, Any]] = {}
        self._item_counter = 0
        self._last_item_interaction: dict[str, Any] = {}
        self._last_crafting: dict[str, Any] = {}
        self._last_trade: dict[str, Any] = {}
        self._economy_state: dict[str, Any] = economy_contract.new_state(
            self._vendor_catalog
        )
        self._dos_history: list[dict[str, Any]] = []
        self._last_dos_command: dict[str, Any] = {}
        self._progression = progression.starter_state()
        self._combat_state = combat_contract.new_state()
        self._combat_target_id = ""
        self._last_combat: dict[str, Any] = {}
        self._character_actions: dict[str, dict[str, Any]] = {}
        self._character_action_serial = 0
        self._ability_cooldowns: dict[str, float] = {}
        self._ability_held: dict[str, bool] = {}
        self._resource = 100.0
        self._last_ability = ""
        self._last_ability_status = "READY"
        self._last_ability_time = -10.0
        self._reset_spells_locked()
        self._reset_survival_locked()
        self._editor_document = editor_contract.new_document()
        self._editor_entity_indices: dict[str, int] = {}
        self._state_store = mmo.MemoryStateStore()
        self._persistence_key = "local-player"
        self._persistence_revision = 0
        # Every local character runtime uses the same account stash. Character
        # saves remain separate from this bounded, durable account inventory.
        self._account_id = "local-account"
        self._stash_store = mmo.LocalAccountStashStore()
        self._stash_state: dict[str, Any] = {"revision": 0, "items": []}
        self._stash_error = ""
        self._open_stash_container_id = ""
        self._open_merchant_id = ""
        try:
            self._stash_state = self._stash_store.load(self._account_id)
        except (OSError, ValueError) as exc:
            self._stash_error = type(exc).__name__ + ":" + str(exc)
        self._terrain_overrides = terrain_contract.new_overrides()
        # Asset admission is intentionally done once at runtime start.  The
        # fixed-step simulation only receives a compact binding view; it never
        # opens or decodes mesh data during a tick or a snapshot.
        self._asset_catalog = assets_contract.default_catalog()
        self._character_creation = character_creation.load_selection()
        self._navigation_cache_key: tuple[Any, ...] | None = None
        self._navigation_tiles: list[dict[str, Any]] = []
        self._navigation_cache_cells: set[tuple[int, int]] = set()
        self._navigation_cache_override_revision: int | None = None
        self._navigation_cache_mode: str | None = None
        self._navigation_interest_center: tuple[int, int] | None = None
        self._navigation_interest_cells: list[dict[str, Any]] = []
        self._terrain_cell_cache: dict[tuple[Any, ...], dict[str, Any]] = {}
        # Full UI snapshots are intentionally richer than the 60 Hz render
        # stream.  The render cache keeps static bindings/geometry metadata
        # stable while the lightweight path refreshes only transforms, poses,
        # item bobbing and particles between full UI snapshots.
        self._render_snapshot_cache: dict[str, Any] | None = None
        self._render_snapshot_signature: tuple[Any, ...] | None = None
        self._dos_live_frame: dict[str, Any] | None = None
        self._dos_live_motion: tuple[Any, ...] | None = None
        self._dos_live_frame_at: float = 0.0
        # The creation preview targets a PS2-like budget by default. The
        # richer profiles remain available in the PERF inspector and game UI.
        self._render_profile = "PS2_CLASSIC"
        self._flora = ecology_contract.FloraStreamer(terrain_contract.DEFAULT_WORLD_SEED)
        self._nature = nature_contract.NatureWorld(terrain_contract.DEFAULT_WORLD_SEED)
        self._presentation_mode = render_contract.RICH_3D
        self._presentation_reason = ""
        self._cinematic_preset = "FIRST_ISLAND_DIORAMA"
        self._tick = 0
        self._sim_time = 0.0
        self._last_tick_ms = 0.0
        self._max_tick_ms = 0.0
        self._network_seq = 0
        self._collision_cooldown = 0.0
        self._particle_cursor = 0
        self._last_xp_visual = None
        self._events: list[dict[str, Any]] = []
        self._event_journal = events_contract.new_journal()
        self._entity_count = 0
        self._particle_count = 0
        self._alive: list[bool] = []
        self._active_entity_indices: list[int] = []
        self._static_entity_indices: list[int] = []
        self._kind: list[str] = []
        self._color: list[str] = []
        self._x: list[float] = []
        self._y: list[float] = []
        self._z: list[float] = []
        self._vx: list[float] = []
        self._vy: list[float] = []
        self._vz: list[float] = []
        self._yaw: list[float] = []
        self._sx: list[float] = []
        self._sy: list[float] = []
        self._sz: list[float] = []
        self._radius: list[float] = []
        self._static: list[bool] = []
        self._npc_indices: list[int] = []
        self._active_particle_indices: list[int] = []
        self._npc_ids: list[str] = []
        self._npc_archetype: list[str] = []
        self._npc_state: list[str] = []
        self._npc_home_x: list[float] = []
        self._npc_home_z: list[float] = []
        self._npc_target_x: list[float] = []
        self._npc_target_z: list[float] = []
        self._npc_phase: list[float] = []
        self._npc_state_time: list[float] = []
        self._npc_decision_speed: list[float] = []
        self._npc_perception_radius: list[float] = []
        self._npc_target_distance: list[float] = []
        self._npc_reason: list[str] = []
        self._npc_last_seen_x: list[float] = []
        self._npc_last_seen_z: list[float] = []
        self._npc_last_seen_age: list[float] = []
        self._npc_line_of_sight: list[bool] = []
        self._npc_stimulus: list[str] = []
        self._npc_interaction_count: list[int] = []
        self._npc_path: list[list[dict[str, float]]] = []
        self._npc_path_index: list[int] = []
        self._npc_path_status: list[str] = []
        self._npc_last_interaction: dict[str, Any] = {}
        self._plife: list[float] = []
        self._px: list[float] = []
        self._py: list[float] = []
        self._pz: list[float] = []
        self._pvx: list[float] = []
        self._pvy: list[float] = []
        self._pvz: list[float] = []
        self._pcolor: list[str] = []
        self._reset_world_locked()

    @staticmethod
    def _default_input() -> dict[str, Any]:
        return {
            "throttle": 0.0,
            "steer": 0.0,
            "turn": 0.0,
            "brake": 0.0,
            "boost": False,
            "forward": 0.0,
            "strafe": 0.0,
            "vertical": 0.0,
            "jump": False,
            "grapple": False,
            "movement_mode": "GROUND",
            "mouse_look": False,
            "facing_yaw": 0.0,
            "camera_yaw": 0.0,
            "camera_pitch": -8.0,
            "camera_distance": world.DEFAULT_CAMERA_DISTANCE_M,
            "ability_1": False,
            "ability_2": False,
            "ability_3": False,
        }

    def _reset_arrays_locked(self) -> None:
        self._alive = [False] * MAX_ENTITIES
        self._active_entity_indices = []
        self._static_entity_indices = []
        self._kind = [""] * MAX_ENTITIES
        self._color = ["#8db89a"] * MAX_ENTITIES
        self._x = [0.0] * MAX_ENTITIES
        self._y = [0.0] * MAX_ENTITIES
        self._z = [0.0] * MAX_ENTITIES
        self._vx = [0.0] * MAX_ENTITIES
        self._vy = [0.0] * MAX_ENTITIES
        self._vz = [0.0] * MAX_ENTITIES
        self._yaw = [0.0] * MAX_ENTITIES
        self._pitch = [0.0] * MAX_ENTITIES
        self._roll = [0.0] * MAX_ENTITIES
        self._sx = [1.0] * MAX_ENTITIES
        self._sy = [1.0] * MAX_ENTITIES
        self._sz = [1.0] * MAX_ENTITIES
        self._radius = [0.5] * MAX_ENTITIES
        self._static = [True] * MAX_ENTITIES
        self._npc_ids = [""] * MAX_ENTITIES
        self._npc_archetype = [""] * MAX_ENTITIES
        self._npc_state = ["WANDER"] * MAX_ENTITIES
        self._npc_home_x = [0.0] * MAX_ENTITIES
        self._npc_home_z = [0.0] * MAX_ENTITIES
        self._npc_target_x = [0.0] * MAX_ENTITIES
        self._npc_target_z = [0.0] * MAX_ENTITIES
        self._npc_phase = [0.0] * MAX_ENTITIES
        self._npc_state_time = [0.0] * MAX_ENTITIES
        self._npc_decision_speed = [0.0] * MAX_ENTITIES
        self._npc_perception_radius = [0.0] * MAX_ENTITIES
        self._npc_target_distance = [0.0] * MAX_ENTITIES
        self._npc_reason = [""] * MAX_ENTITIES
        self._npc_last_seen_x = [0.0] * MAX_ENTITIES
        self._npc_last_seen_z = [0.0] * MAX_ENTITIES
        self._npc_last_seen_age = [60.0] * MAX_ENTITIES
        self._npc_line_of_sight = [False] * MAX_ENTITIES
        self._npc_stimulus = ["NONE"] * MAX_ENTITIES
        self._npc_interaction_count = [0] * MAX_ENTITIES
        self._npc_path = [[] for _ in range(MAX_ENTITIES)]
        self._npc_path_index = [0] * MAX_ENTITIES
        self._npc_path_status = ["NOT_REQUESTED"] * MAX_ENTITIES
        self._npc_path_goal_tile: list[tuple[int, int] | None] = [None] * MAX_ENTITIES
        self._npc_path_navigation_key: list[tuple[Any, ...] | None] = [None] * MAX_ENTITIES
        self._npc_path_attempt_tick = [-60] * MAX_ENTITIES
        self._plife = [0.0] * MAX_PARTICLES
        self._active_particle_indices = []
        self._px = [0.0] * MAX_PARTICLES
        self._py = [0.0] * MAX_PARTICLES
        self._pz = [0.0] * MAX_PARTICLES
        self._pvx = [0.0] * MAX_PARTICLES
        self._pvy = [0.0] * MAX_PARTICLES
        self._pvz = [0.0] * MAX_PARTICLES
        self._pcolor = ["#c8a97e"] * MAX_PARTICLES
        self._reset_ride_particles_locked()

    def _free_entity_locked(self) -> int | None:
        for index in range(1, MAX_ENTITIES):
            if not self._alive[index]:
                return index
        return None

    def _despawn_entity_locked(self, index: int) -> bool:
        if index <= 0 or index >= MAX_ENTITIES or not self._alive[index]:
            return False
        self._alive[index] = False
        self._active_entity_indices.remove(index)
        if self._static[index]:
            self._static_entity_indices.remove(index)
        if index in self._npc_indices:
            self._npc_indices.remove(index)
        self._npc_ids[index] = ""
        self._npc_archetype[index] = ""
        self._npc_state[index] = "WANDER"
        self._npc_last_seen_x[index] = 0.0
        self._npc_last_seen_z[index] = 0.0
        self._npc_last_seen_age[index] = 60.0
        self._npc_line_of_sight[index] = False
        self._npc_stimulus[index] = "NONE"
        self._npc_interaction_count[index] = 0
        self._npc_path[index] = []
        self._npc_path_index[index] = 0
        self._npc_path_status[index] = "NOT_REQUESTED"
        self._npc_path_goal_tile[index] = None
        self._npc_path_navigation_key[index] = None
        self._npc_path_attempt_tick[index] = -60
        self._kind[index] = ""
        self._entity_count = max(0, self._entity_count - 1)
        return True

    def _terrain_height_locked(self, x: float, z: float, *, static: bool = False) -> float:
        """Cache exact samples; movers never evict fixed flora/animal anchors."""
        imported=getattr(self,'_engine_world',None)
        if imported is not None:return imported.ground(x,self._y[0],z)
        revision = int(self._terrain_overrides.get("revision", 0))
        if (revision != getattr(self, "_height_cache_revision", None)
                or self._terrain_overrides is not getattr(self, "_height_cache_document", None)):
            self._height_cache_revision = revision
            self._height_cache_document = self._terrain_overrides
            self._height_samples = OrderedDict()
            self._static_height_samples = OrderedDict()
            self._height_brush_stamps = terrain_contract._normalized_brush_stamps(self._terrain_overrides)
            self._height_brush_index = terrain_contract._build_brush_index(self._height_brush_stamps)
        key = (x, z)
        cache = self._static_height_samples if static else self._height_samples
        if key in cache:
            cache.move_to_end(key)
            return cache[key]
        value = terrain_contract.height_at(
            x, z, WORLD_SEED, overrides=self._terrain_overrides,
            brush_stamps=self._height_brush_stamps, brush_index=self._height_brush_index,
        )
        cache[key] = value
        limit = STATIC_HEIGHT_CACHE_LIMIT if static else MOVING_HEIGHT_CACHE_LIMIT
        if len(cache) > limit:
            cache.popitem(last=False)
        return value

    def _static_terrain_height_locked(self, x: float, z: float) -> float:
        return self._terrain_height_locked(x, z, static=True)

    def _water_sample_locked(self, x: float, z: float) -> dict[str, Any]:
        if getattr(self,'_engine_world',None) is not None:
            return self._engine_world.water_sample(x,self._y[0],z)
        from backend.game_engine_landscape import water_at
        inland=water_at(x,z)
        if inland is not None:
            slope=inland['slope'];length=math.sqrt(1+slope['x']**2+slope['z']**2)
            return {'height_m':inland['level_m'],'slope':slope,
                    'current_mps':inland['current_mps'],'vertical_velocity_mps':0.,
                    'normal':{'x':-slope['x']/length,'y':1/length,'z':-slope['z']/length},'wave_height_m':0.,
                    'surface_model':'AUTHORED_INLAND_WATER','body_id':inland['id'],'body_kind':inland['kind']}
        return mobility_contract.surface_sample(
            x,
            z,
            self._sim_time,
            sea_level_m=terrain_contract.SEA_LEVEL,
        )

    def _water_depth_locked(self, x: float, z: float) -> float:
        return max(
            0.0,
            float(self._water_sample_locked(x, z)["height_m"])
            - self._terrain_height_locked(x, z),
        )

    def _player_surface_locked(self) -> dict[str, Any]:
        """Fresh controller/provider facts, shared by render, UI and Lua/audio."""
        x,z=self._x[0],self._z[0];height=self._terrain_height_locked(x,z);water=self._water_sample_locked(x,z)
        depth=max(0.,water['height_m']-height)
        if self._vehicle_kind=='BOAT' or self._movement_mode=='SWIM':medium='WATER'
        elif self._movement_mode=='FLY':medium='AIR'
        elif depth>mobility_contract.MIN_SWIMMABLE_DEPTH_M and self._y[0]<=water['height_m']+1.5:medium='WATER'
        else:medium='LAND'
        return {'height_m':height,'medium':medium,'water_depth_m':depth,'water_height_m':water['height_m'],
                'biome':'WORLD' if getattr(self,'_engine_world',None) is not None else planet_contract.biome_at(x,z,WORLD_SEED),
                'liquid_kind':water.get('body_kind','WATER' if depth>0 else 'NONE')}

    def _ground_contact_height_locked(
        self,
        x: float,
        z: float,
        *,
        vehicle_kind: str = "NONE",
    ) -> float:
        terrain_y = self._terrain_height_locked(x, z)
        if getattr(self,'_engine_world',None) is not None:return terrain_y+mobility_contract.PLAYER_ROOT_HEIGHT_M
        floor_y = terrain_y + mobility_contract.PLAYER_ROOT_HEIGHT_M
        from backend.game_engine_landscape import contact_height
        landscape_floor=contact_height(x,z,self._y[0],self._static_terrain_height_locked)
        if landscape_floor is not None:floor_y=landscape_floor
        if vehicle_kind == "HOVERBOARD":
            if self._water_depth_locked(x, z) > mobility_contract.MIN_SWIMMABLE_DEPTH_M:
                # Same sample the mesh draws. The seabed only stops the
                # board falling through the beach, it is not a second sea.
                return max(
                    floor_y + mobility_contract.HOVER_RIDE_HEIGHT_M,
                    float(self._water_sample_locked(x, z)["height_m"])
                    + mobility_contract.HOVER_WATER_CLEARANCE_M,
                )
            return floor_y + mobility_contract.HOVER_RIDE_HEIGHT_M
        if vehicle_kind == "NONE":
            from backend.game_engine_canopy import contact_height as canopy_contact
            canopy_floor=canopy_contact(x,z,self._y[0],self._static_terrain_height_locked)
            if canopy_floor is not None:floor_y=max(floor_y,canopy_floor)
            if landscape_floor is not None:return max(floor_y,landscape_floor)
            place_floor=world_places_contract.building_floor(x,z,self._y[0],self._static_terrain_height_locked)
            if place_floor is not None:return max(floor_y,place_floor)
            roof_y = self._house_roof_height_locked(x, z)
            # Only claim the roof once the body is already up there, so a
            # jump can pass the walls instead of snapping onto the thatch.
            if roof_y is not None and self._y[0] >= roof_y - 0.12:
                return max(floor_y,roof_y)
            deck_y = self._house_deck_height_locked(x, z)
            if deck_y is not None:
                return max(floor_y,deck_y)
        return floor_y

    def _spawn_entity_locked(
        self,
        kind: str,
        x: float,
        y: float,
        z: float,
        scale: tuple[float, float, float],
        color: str,
        radius: float,
        *,
        static: bool = True,
        index: int | None = None,
    ) -> int | None:
        slot = index if index is not None else self._free_entity_locked()
        if slot is None or slot < 0 or slot >= MAX_ENTITIES:
            return None
        if self._alive[slot]:
            return None
        self._alive[slot] = True
        bisect.insort(self._active_entity_indices, slot)
        self._kind[slot] = str(kind)
        self._color[slot] = str(color)
        self._x[slot] = float(x)
        self._y[slot] = float(y)
        self._z[slot] = float(z)
        self._vx[slot] = 0.0
        self._vy[slot] = 0.0
        self._vz[slot] = 0.0
        self._yaw[slot] = 0.0
        self._pitch[slot] = 0.0
        self._roll[slot] = 0.0
        self._sx[slot], self._sy[slot], self._sz[slot] = scale
        self._radius[slot] = float(radius)
        self._static[slot] = bool(static)
        if self._static[slot]:
            bisect.insort(self._static_entity_indices, slot)
        self._entity_count += 1
        return slot

    def _house_local_locked(self, index: int, px: float, pz: float) -> tuple[float, float]:
        sx = max(0.15, abs(float(self._sx[index])))
        sz = max(0.15, abs(float(self._sz[index])))
        return (px - self._x[index]) / sx, (pz - self._z[index]) / sz

    def _house_deck_height_locked(self, px: float, pz: float) -> float | None:
        """Walkable deck and ladder for enterable stilt huts."""
        deck_y = assets_contract.HUT_DECK_LOCAL_Y
        deck_hx = assets_contract.HUT_DECK_HX
        deck_hz = assets_contract.HUT_DECK_HZ
        door_half = assets_contract.HUT_DOOR_HALF
        ladder_z = assets_contract.HUT_LADDER_Z
        for index in self._static_entity_indices:
            if self._kind[index] != "HOUSE":
                continue
            lx, lz = self._house_local_locked(index, px, pz)
            sy = max(0.15, abs(float(self._sy[index])))
            deck_world = self._y[index] + deck_y * sy + 0.65
            if abs(lx) <= deck_hx and abs(lz) <= deck_hz:
                return deck_world
            if abs(lx) <= door_half and ladder_z - 0.14 <= lz <= -deck_hz:
                span = max(0.08, -deck_hz - (ladder_z - 0.14))
                t = max(0.0, min(1.0, (lz - (ladder_z - 0.14)) / span))
                terrain = self._terrain_height_locked(px, pz) + 0.65
                return terrain + (deck_world - terrain) * t
        return None

    def _house_roof_height_locked(self, px: float, pz: float) -> float | None:
        """Player-root height of a hut roof. Feet sit on the visual crown."""
        for index in self._static_entity_indices:
            if self._kind[index] != "HOUSE":
                continue
            lx, lz = self._house_local_locked(index, px, pz)
            if abs(lx) > assets_contract.HUT_DECK_HX * 1.12:
                continue
            if abs(lz) > assets_contract.HUT_DECK_HZ * 1.12:
                continue
            sy = max(0.15, abs(float(self._sy[index])))
            return (
                self._y[index]
                + sy
                + mobility_contract.PLAYER_ROOT_HEIGHT_M
            )
        return None

    def _tick_house_walls_locked(self) -> None:
        """Solid walls with a door hole — the hut is a room, not a blob."""
        imported=getattr(self,'_engine_world',None)
        if imported is not None:
            self._x[0],self._z[0]=imported.collide(self._x[0],self._y[0],self._z[0]);return
        from backend.game_engine_landscape import cave_collision
        self._x[0],self._z[0],self._y[0]=cave_collision(self._x[0],self._z[0],self._y[0])
        self._x[0],self._z[0]=world_places_contract.building_walls(
            self._x[0],self._z[0],self._y[0],self._static_terrain_height_locked)
        wall_hx = assets_contract.HUT_WALL_HX
        wall_hz = assets_contract.HUT_WALL_HZ
        wall_t = assets_contract.HUT_WALL_T
        door_half = assets_contract.HUT_DOOR_HALF
        clearance = assets_contract.HUT_PLAYER_CLEARANCE
        wing = (wall_hx - door_half) * 0.5
        walls = (
            (0.0, wall_hz, wall_hx + wall_t, wall_t),
            (-wall_hx, 0.0, wall_t, wall_hz),
            (wall_hx, 0.0, wall_t, wall_hz),
            (-door_half - wing, -wall_hz, wing + wall_t, wall_t),
            (door_half + wing, -wall_hz, wing + wall_t, wall_t),
        )
        px, pz = self._x[0], self._z[0]
        for index in self._static_entity_indices:
            if self._kind[index] != "HOUSE":
                continue
            sx = max(0.15, abs(float(self._sx[index])))
            sz = max(0.15, abs(float(self._sz[index])))
            roof_y = (
                self._y[index]
                + max(0.15, abs(float(self._sy[index])))
                + mobility_contract.PLAYER_ROOT_HEIGHT_M
            )
            if self._y[0] >= roof_y - 0.12:
                continue
            lx, lz = self._house_local_locked(index, px, pz)
            if abs(lx) > assets_contract.HUT_DECK_HX + 0.4:
                continue
            if abs(lz) > assets_contract.HUT_DECK_HZ + 0.4:
                continue
            in_door = abs(lx) <= door_half + 0.04 and -wall_hz - 0.2 <= lz <= -wall_hz + 0.18
            moved = False
            for cx, cz, hx, hz in walls:
                if in_door and abs(cz + wall_hz) < 0.02:
                    continue
                dx = lx - cx
                dz = lz - cz
                overlap_x = hx + clearance - abs(dx)
                overlap_z = hz + clearance - abs(dz)
                if overlap_x <= 0.0 or overlap_z <= 0.0:
                    continue
                if overlap_x < overlap_z:
                    sign = -1.0 if dx >= 0.0 else 1.0
                    lx += sign * overlap_x
                else:
                    sign = -1.0 if dz >= 0.0 else 1.0
                    lz += sign * overlap_z
                moved = True
            if not moved:
                continue
            self._x[0] = self._x[index] + lx * sx
            self._z[0] = self._z[index] + lz * sz
            px, pz = self._x[0], self._z[0]

    def _spawn_npc_locked(
        self,
        spawn: dict[str, Any],
        *,
        index: int | None = None,
    ) -> int | None:
        """Create one NPC in the shared entity pool and its sidecar data."""
        if not isinstance(spawn, dict):
            return None
        archetype = npc_contract.normalize_archetype(spawn.get("archetype"))
        x = _clamp(spawn.get("x"), -1000000.0, 1000000.0)
        z = _clamp(spawn.get("z"), -1000000.0, 1000000.0)
        raw_scale = spawn.get("scale", (1.0, 1.0, 1.0))
        if not isinstance(raw_scale, (list, tuple)) or len(raw_scale) < 3:
            raw_scale = (1.0, 1.0, 1.0)
        scale = (
            max(0.35, min(3.0, abs(_clamp(raw_scale[0], 0.35, 3.0, 1.0)))),
            max(0.35, min(3.0, abs(_clamp(raw_scale[1], 0.35, 3.0, 1.0)))),
            max(0.35, min(3.0, abs(_clamp(raw_scale[2], 0.35, 3.0, 1.0)))),
        )
        color = str(spawn.get("color", "#d7a36f") or "#d7a36f")[:16]
        slot = self._spawn_entity_locked(
            "NPC",
            x,
            self._terrain_height_locked(x, z) + 0.65,
            z,
            scale,
            color,
            0.75,
            static=False,
            index=index,
        )
        if slot is None:
            return None
        profile = npc_contract.profile_for(archetype)
        npc_id = str(spawn.get("id", "") or f"npc-{slot:04d}")[:48]
        phase = _clamp(spawn.get("phase"), -1000.0, 1000.0)
        self._npc_indices.append(slot)
        self._npc_ids[slot] = npc_id
        self._npc_archetype[slot] = archetype
        self._npc_state[slot] = "WANDER"
        self._npc_home_x[slot] = x
        self._npc_home_z[slot] = z
        self._npc_target_x[slot] = x
        self._npc_target_z[slot] = z
        self._npc_phase[slot] = phase
        self._npc_state_time[slot] = 0.0
        self._npc_decision_speed[slot] = profile["speed"]
        self._npc_perception_radius[slot] = profile["sense_radius"]
        self._npc_target_distance[slot] = 0.0
        self._npc_reason[slot] = "SPAWN"
        self._npc_last_seen_x[slot] = x
        self._npc_last_seen_z[slot] = z
        self._npc_last_seen_age[slot] = 60.0
        self._npc_line_of_sight[slot] = False
        self._npc_stimulus[slot] = "NONE"
        self._npc_interaction_count[slot] = 0
        self._npc_path[slot] = []
        self._npc_path_index[slot] = 0
        self._npc_path_status[slot] = "NOT_REQUESTED"
        self._npc_path_goal_tile[slot] = None
        self._npc_path_navigation_key[slot] = None
        self._npc_path_attempt_tick[slot] = -60
        identity_contract.ensure_individual(
            self._individual_state,
            npc_id,
            archetype=archetype,
            role=archetype,
            home={"x": x, "y": 0.0, "z": z},
        )
        return slot

    def _set_life_spawns_locked(self, rows: list[dict[str, Any]]) -> None:
        """Place authored villagers on the expanded island once."""
        feel = world.ISLAND_LAYOUT_SCALE
        expanded: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            if row.get("world_feel_applied"):
                expanded.append(row)
                continue
            placed = dict(row)
            placed["x"] = float(placed.get("x", 0.0)) * feel
            placed["z"] = float(placed.get("z", 0.0)) * feel
            if "radius" in placed:
                placed["radius"] = float(placed["radius"]) * feel
            if "sense_radius" in placed:
                placed["sense_radius"] = min(16.0, float(placed["sense_radius"]) * feel)
            if placed.get("waypoints"):
                placed["waypoints"]=[{**point,"x":point["x"]*feel,"z":point["z"]*feel}
                                     for point in placed["waypoints"]]
                life_contract.prepare_routine(placed)
            placed["world_feel_applied"] = True
            expanded.append(placed)
        self._life_spawns = expanded
        if hasattr(self,"_individual_state"):
            self._ensure_life_individuals_locked()

    def _ensure_life_individuals_locked(self) -> None:
        """Every authored resident owns a durable identity at the saved home."""
        for spawn in self._life_spawns:
            home={"x":spawn["x"],"y":0.,"z":spawn["z"]}
            identity=str(spawn["id"])
            existed=identity in self._individual_state.get("individuals",{})
            person=identity_contract.ensure_individual(self._individual_state,identity,
                role=spawn.get("role","VILLAGER"),home=home)
            if person.get("id")!=identity:continue
            person["home"]=home
            if not existed:
                person["occupation"]=spawn.get("role","VILLAGER")
                if spawn.get("name"):person["name"]=spawn["name"]

    def _ecology_view_locked(self) -> dict[str, Any]:
        view = dict(self._flora.update(
            self._x[0], self._z[0], profile=self._render_profile,
            terrain_revision=int(self._terrain_overrides.get("revision", 0)),
            height_at=self._static_terrain_height_locked,
        ))
        self._refresh_nature_locked()
        signature=(self._flora._revision,tuple((key,state.get("hidden_until",0)>self._sim_time)
            for key,state in self._nature.states.items() if state.get("hidden_until")))
        if signature != getattr(self,"_flora_visibility_signature",None):
            self._flora_visibility_signature=signature
            self._flora_visible_revision=getattr(self,"_flora_visible_revision",0)+1
            self._flora_visible_counts={key:sum(self._nature.visible(r["id"],self._sim_time) for r in rows)
                for key,rows in self._flora.groups.items()}
        view["revision"]=self._flora_visible_revision
        view["groups"]=self._flora_visible_counts
        view["land_fauna"] = "SHARED_NEARBY_NATURE_SIMULATION"
        view["collision"] = "FLORA_DECORATIVE_WITH_AUTHORITATIVE_HARVEST_TARGETS"
        return view

    def _refresh_nature_locked(self) -> None:
        if getattr(self,"_nature_flora_revision",None)!=self._flora._revision:
            self._nature_flora_revision=self._flora._revision
            self._nature_plant_rows=[r for rows in self._flora.groups.values() for r in rows if r["species"] in nature_catalog.PLANTS]
        self._nature.update(self._x[0], self._z[0], self._sim_time,
                            self._terrain_height_locked, self._nature_plant_rows,
                            int(self._terrain_overrides.get("revision", 0)),
                            static_height_at=self._static_terrain_height_locked)
        self._publish_companions_locked()

    def _nature_view_locked(self) -> dict[str, Any]:
        self._refresh_nature_locked()
        return {"schema": nature_contract.SCHEMA, "revision": self._nature.revision,
                "groups": {k:len(v) for k,v in self._nature.groups.items() if v},
                "target": self._nature.target(self._x[0],self._y[0],self._z[0],self._sim_time,self._inventory),
                "last_result": self._nature.last_result, "species_count": len(nature_catalog.SPECIES),
                "animal_cap": nature_contract.MAX_ANIMALS, "resident_cells": len(self._nature.cells)}

    def nature_batch(self, key: str) -> tuple[list[dict], int]:
        with self._lock:
            return list(self._nature.groups.get(key, ())), self._nature.revision

    def nature_action(self, target_id: str = "", action: str = "") -> dict[str, Any]:
        with self._lock:
            self._ecology_view_locked()
            target = self._nature.target(self._x[0],self._y[0],self._z[0],self._sim_time,self._inventory,str(target_id or ""))
            wanted = str(action or "").upper()
            if not wanted:
                wanted = next((a["id"] for a in target.get("actions",[]) if a["ready"] and a["id"] not in {"ATTACK","PET"}), "PET")
            prepared = self._nature.prepare(str(target_id or target.get("id", "")),wanted,
                            self._x[0],self._y[0],self._z[0],self._sim_time,self._inventory)
            if "error" in prepared:
                self._nature.last_result=prepared
                snapshot=self.snapshot_locked();snapshot["error"]=prepared["error"];return snapshot
            # Plan the item transfer before consuming a plant/animal cooldown.
            reward=None;stack=None
            if prepared["table_id"]:
                roll=item_state.roll_loot(self._item_catalog,prepared["seed"],prepared["table_id"])
                definition_id=roll.get("item_id", "")
                if not definition_id or item_state.definition(self._item_catalog,definition_id) is None:
                    snapshot=self.snapshot_locked();snapshot["error"]="NATURE_LOOT_DEFINITION_MISSING";return snapshot
                quantity=int(roll.get("quantity",1));definition=item_state.definition(self._item_catalog,definition_id)
                stack=next((r for r in self._item_instances.values() if r.get("definition_id")==definition_id
                            and r.get("location")=="INVENTORY" and r.get("owner_id")=="player"
                            and r.get("quantity",1)+quantity<=definition.get("stack_limit",1)),None)
                slots=sum(r.get("location")=="INVENTORY" and r.get("owner_id")=="player" for r in self._item_instances.values())
                if stack is None and (slots>=item_state.MAX_INVENTORY_SLOTS or len(self._item_instances)>=item_state.MAX_WORLD_INSTANCES):
                    error="ITEM_INVENTORY_FULL" if slots>=item_state.MAX_INVENTORY_SLOTS else "ITEM_INSTANCE_CAPACITY"
                    self._nature.last_result={"error":error}
                    snapshot=self.snapshot_locked();snapshot["error"]=error;return snapshot
                reward={"definition_id":definition_id,"quantity":quantity,"name":definition["name"]}
            if reward:
                if stack:stack["quantity"]+=reward["quantity"]
                else:
                    instance_id=self._next_item_instance_id_locked("nature")
                    instance=item_state.make_instance(self._item_catalog,instance_id,reward["definition_id"],
                                                      quantity=reward["quantity"],location="INVENTORY")
                    instance.update(origin="NATURE",roll_table_id=prepared["table_id"])
                    self._item_instances[instance_id]=instance
                self._inventory=item_state.inventory_counts(self._item_instances.values())
                self._ensure_inventory_slots_locked()
            self._nature.commit(prepared)
            self._nature.last_result["loot"]=reward or {}
            self._append_event_locked("NATURE_INTERACTION",prepared["name"]+" · "+nature_catalog.LABELS[wanted],
                                      actor_id="player",subject_id=prepared["id"],payload=self._nature.last_result)
            return self.snapshot_locked()

    def ecology_batch(self, key: str) -> tuple[list[dict], int]:
        """Read cached data for Qt; never build a snapshot per plant delegate."""
        with self._lock:
            return [r for r in self._flora.groups.get(key, ()) if self._nature.visible(r["id"],self._sim_time)], getattr(self,"_flora_visible_revision",0)

    def _fauna_view_locked(self) -> dict[str, Any]:
        stamp=(int(self._sim_time*2),int(self._x[0]/32),int(self._z[0]/32))
        if getattr(self,"_fauna_stamp",None)==stamp:return self._fauna_cached
        value = fauna_contract.build_groups(
            self._x[0],
            self._z[0],
            self._sim_time,
            sea_level=terrain_contract.SEA_LEVEL,
            island_radius=world.island_half_extent_m(),
            height_at=self._terrain_height_locked,
            water_at=lambda x, z: mobility_contract.surface_sample(
                x, z, self._sim_time,
                sea_level_m=terrain_contract.SEA_LEVEL,
            )["height_m"],
        )
        self._fauna_stamp=stamp;self._fauna_cached=value
        return value

    def _reset_world_locked(self) -> None:
        self._rigid_physics.reset()
        self._published_frame = None
        self._published_nature = None
        self._nature = nature_contract.NatureWorld(terrain_contract.DEFAULT_WORLD_SEED)
        if not hasattr(self,'_actions'):self._actions=actions_contract.ActionBars()
        self._actions.auto_attack=False;self._actions.history=[]
        self._height_cache_revision=None
        self._action_item_cooldowns={}
        self._flora_visibility_signature=None
        self._fauna_stamp=None
        self._ui_snapshot_base=None
        self._nature_flora_revision=None
        self._reset_arrays_locked()
        self._world_population = WorldPopulation()
        self._world_actor_assets = {}
        self._set_life_spawns_locked(life_contract.spawns_from_content(self._content))
        self._world_event_catalog = world_events_contract.normalized_catalog(
            self._content.get("world_events")
        )
        self._world_event_state = world_events_contract.new_state()
        self._npc_indices = []
        self._entity_count = 0
        self._particle_count = 0
        self._particle_cursor = 0
        self._last_xp_visual = None
        self._collision_cooldown = 0.0
        self._tick = 0
        self._sim_time = 0.0
        self._network_seq = 0
        self._events = []
        self._event_journal = events_contract.new_journal()
        self._input = self._default_input()
        self._movement_mode = "GROUND"
        self._vehicle_kind = "NONE"
        self._boat_entity_index = None
        self._locomotion_distance_m = 0.0
        self._camera_yaw = 0.0
        self._camera_pitch = -8.0
        self._camera_distance = world.DEFAULT_CAMERA_DISTANCE_M
        self._reset_client_controls_locked()
        self._reset_spells_locked()
        self._reset_survival_locked()
        self._jump_held = False
        self._jump_count = 0
        self._double_jump_pose_remaining_s = 0.0
        self._coyote_time_remaining_s = 0.0
        self._jump_buffer_remaining_s = 0.0
        self._jump_hold_time_s = 0.0
        self._grapple_held = False
        self._grapple_anchor = None
        self._grapple_rope_length = 0.0
        self._grapple_projectile = None
        self._firearm_shots=[]
        self._firearm_last_hand=""
        self._grounded = True
        self._sprinting = False
        self._item_instances = {
            str(row["instance_id"]): row
            for row in item_state.starter_instances(self._item_catalog)
            if isinstance(row, dict) and row.get("instance_id")
        }
        self._item_counter = 0
        for tool in nature_catalog.TOOLS:
            instance_id="nature-tool-"+tool
            self._item_instances[instance_id]=item_state.make_instance(
                self._item_catalog,instance_id,"item.nature.tool_"+tool,location="INVENTORY")
        self._individual_state = identity_contract.runtime_state(self._people_catalog)
        self._ensure_life_individuals_locked()
        self._faction_state = factions_contract.new_state(self._people_catalog.values())
        self._quest_state = quests_contract.new_state()
        self._quest_visit_presence = set()
        self._dialogue_state = dialogue_contract.new_state()
        self._engine_quest_panel={};self._engine_gossip_hidden=False
        self._social_state = social_contract.new_state()
        self._promoted_life_ids = set()
        self._last_population_promotion_s = 0.0
        self._seed_active_pack_world_items_locked()
        self._materialize_npc_item_instances_locked()
        self._refresh_all_npc_progression_locked()
        self._inventory = item_state.inventory_counts(self._item_instances.values())
        self._profession_state = copy.deepcopy(
            self._gear_tables.get("professions", {})
        )
        self._loot_items = []
        self._loot_counter = 0
        self._last_item_interaction = {}
        self._open_stash_container_id = ""
        self._open_merchant_id = ""
        self._engine_loot = {}
        self._engine_craft_book = {}
        self._engine_craft_repeat = {}
        self._engine_craft_error = ''
        self._last_crafting = {}
        self._last_trade = {}
        self._economy_state = economy_contract.new_state(self._vendor_catalog)
        self._dos_history = []
        self._last_dos_command = {}
        self._progression = progression.starter_state()
        self._combat_state = combat_contract.new_state()
        self._last_combat = {}
        self._character_actions = {}
        self._character_action_serial = 0
        self._combat_target_id = ""
        self._ability_cooldowns = {}
        self._ability_held = {}
        self._resource = 100.0
        self._last_ability = ""
        self._last_ability_status = "READY"
        self._last_ability_time = -10.0
        self._editor_document = editor_contract.new_document()
        self._editor_entity_indices = {}
        self._npc_last_interaction = {}
        self._terrain_overrides = terrain_contract.new_overrides()
        self._terrain_cell_cache.clear()
        self._navigation_cache_key = None
        self._navigation_tiles = []
        self._navigation_cache_cells.clear()
        self._navigation_cache_override_revision = None
        self._navigation_cache_mode = None
        self._navigation_interest_center = None
        self._navigation_interest_cells = []
        self._render_snapshot_cache = None
        self._render_snapshot_signature = None
        self._dos_live_frame = None
        self._dos_live_motion = None
        self._dos_live_frame_at = 0.0

        self._spawn_entity_locked(
            "PLAYER",
            0.0,
            self._terrain_height_locked(0.0, 0.0) + 0.65,
            0.0,
            (1.0, 1.0, 1.0),
            "#d4a85a",
            1.1,
            static=False,
            index=0,
        )
        # Original tropical coast village: clustered stilt huts around an
        # open green, a path down to the sheltered cove, distinct shore plants,
        # working village details and a windmill on the west headland. Keep the
        # bounded island cast while giving the village distinct shore and
        # cove landmarks made in the visible Blender asset pipeline.
        village: tuple[tuple[str, float, float, tuple[float, float, float], str, float], ...] = (
            ("HOUSE", -5.8, 4.0, (1.58, 1.72, 1.58), "#d7824a", 0.8),
            ("HOUSE", -1.5, 7.6, (1.62, 1.78, 1.62), "#cf7342", 0.8),
            ("HOUSE", 4.7, 6.4, (1.58, 1.72, 1.58), "#d98a4b", 0.8),
            ("HOUSE", 7.2, 1.0, (1.62, 1.80, 1.62), "#c96e3f", 0.8),
            ("HOUSE", 6.3, -5.0, (1.55, 1.70, 1.55), "#dd9250", 0.8),
            ("HOUSE", 1.2, -8.1, (1.60, 1.78, 1.60), "#c86c3e", 0.8),
            ("HOUSE", -5.7, -6.6, (1.58, 1.74, 1.58), "#dc8a4b", 0.8),
            ("PALM", 15.0, 6.0, (0.88, 2.05, 0.88), "#4aaa3a", 0.9),
            ("PALM", 15.0, -4.0, (0.92, 2.18, 0.92), "#3d9a32", 0.85),
            ("PALM", 2.0, 15.0, (0.95, 2.16, 0.95), "#56b844", 0.95),
            ("PALM", -14.0, 2.0, (0.91, 2.12, 0.91), "#48a838", 0.88),
            ("PALM", -9.0, 10.0, (0.94, 2.22, 0.94), "#4aaa3a", 0.92),
            ("PALM", 24.0, 4.5, (0.98, 2.32, 0.98), "#56b844", 1.00),
            ("PALM", -23.0, -4.0, (0.96, 2.30, 0.96), "#48a838", 1.00),
            ("BARREL", -9.0, -13.0, (0.42, 0.48, 0.42), "#80502d", 0.45),
            ("MANGROVE", -10.0, -18.0, (0.92, 1.58, 0.92), "#397c43", 0.85),
            ("MANGROVE", -1.0, -19.0, (0.98, 1.62, 0.98), "#397c43", 0.9),
            ("MANGROVE", 4.0, -14.0, (0.90, 1.55, 0.90), "#397c43", 0.82),
            ("ROCK", -18.0, 4.0, (1.45, 0.92, 1.25), "#8d684b", 1.0),
            ("ROCK", -16.0, -11.0, (1.35, 0.90, 1.18), "#8d684b", 0.95),
            ("PROP", -2.0, 8.0, (0.72, 0.92, 0.72), "#9a6b45", 0.65),
            ("DOCK", -2.0, -20.0, (1.10, 1.40, 1.20), "#c9a06a", 3.0),
            ("WATER_WHEEL", 9.0, -13.0, (2.05, 2.00, 1.12), "#b77a41", 2.2),
            ("WINDMILL", -11.0, -10.0, (2.10, 3.80, 2.10), "#d96b4a", 1.1),
            ("MARKET_STALL", -3.0, 4.5, (1.28, 1.10, 0.98), "#d9a14c", 0.9),
            ("FISH_RACK", -7.0, -14.5, (0.82, 0.82, 0.70), "#c28b53", 0.7),
            # The skiff begins at the accessible mouth of the cove, close to
            # the pier but in enough depth to float at every tide phase.
            ("BOAT", -3.0, -21.5, (0.76, 0.46, 1.45), "#80502d", 1.0),
            ("BRIDGE", -4.0, -16.2, (0.65, 0.55, 1.50), "#b77a41", 1.0),
            ("LIGHT", 3.0, -3.0, (0.36, 0.95, 0.36), "#ffd278", 0.6),
            ("LIGHT", -4.0, 3.0, (0.36, 0.95, 0.36), "#ffd278", 0.6),
            # House stairs are part of the authored kit. The two detached
            # legacy ramps no longer serve an entrance in the enlarged layout.
            ("PATH", 0.0, -4.0, (1.05, 0.35, 1.80), "#c4a070", 0.4),
            ("PATH", -0.4, -7.2, (1.05, 0.35, 1.80), "#b89060", 0.4),
            ("PATH", -1.0, -10.4, (1.05, 0.35, 1.80), "#c8b48a", 0.4),
            ("PATH", -2.0, -13.6, (1.05, 0.35, 1.80), "#bca87a", 0.4),
        )
        feel = world.WORLD_PROP_SCALE
        layout = world.ISLAND_LAYOUT_SCALE
        for kind, prop_x, prop_z, scale, color, radius_m in village:
            sx, sy, sz = (float(scale[0]), float(scale[1]), float(scale[2]))
            if kind == "HOUSE":
                # Keep the approved architecture height independent of the
                # character's jump and the horizontal island layout.
                sy = world.HOUSE_ROOF_CLEARANCE_M / 2.0
            prop_x *= layout
            prop_z *= layout
            if kind == "BOAT":
                # Sized to the character, not to the old toy hull.
                sx, sy, sz = mobility_contract.SKIFF_SCALE
            else:
                sx *= feel
                sy *= feel
                sz *= feel
                if kind in {"PATH", "DOCK", "BRIDGE"}:
                    # Preserve connected village routes as placements spread apart.
                    sx *= layout / feel
                    sz *= layout / feel
            scale = (sx, sy, sz)
            prop_y = self._terrain_height_locked(prop_x, prop_z) + sy
            if kind == "DOCK":
                # The cove pier spans its low beach and the shallow waterline.
                prop_y = sy * 0.38 + 0.60 * world.WORLD_FEEL_SCALE
            elif kind == "BOAT":
                # The hull's inside rim is authored at its local waterline.
                prop_y = sy * 0.30
            elif kind == "BRIDGE":
                # Match the pier deck through the shallow cove approach.
                prop_y = sy * 0.39 + 0.60 * world.WORLD_FEEL_SCALE
            elif kind == "MANGROVE" and prop_y < sy:
                # Rooted mangroves planted at the tide edge start at sea level;
                # the imported root flare can extend below the water surface.
                prop_y = sy
            slot = self._spawn_entity_locked(
                kind,
                prop_x,
                prop_y,
                prop_z,
                scale,
                color,
                3.4 if kind == "BOAT" else radius_m * feel,
            )
            if kind == "BOAT":
                self._boat_entity_index = slot
                if slot is not None:
                    # The skiff is spawned at the north edge of the southern
                    # cove; point its default forward input toward the deeper
                    # channel, away from the dock and the shallow beach.
                    self._yaw[slot] = math.pi
                    self._y[slot] = mobility_contract.surface_sample(
                        prop_x, prop_z, self._sim_time,
                        sea_level_m=terrain_contract.SEA_LEVEL,
                    )["height_m"] + mobility_contract.BOAT_HULL_DRAFT_M

        beacon_x, beacon_z = 4.0 * layout, -22.0 * layout
        self._spawn_entity_locked(
            "TIDE_BEACON",
            beacon_x,
            self._terrain_height_locked(beacon_x, beacon_z) + 1.46 * feel,
            beacon_z,
            (0.80 * feel, 1.46 * feel, 0.80 * feel),
            "#e5bd69",
            0.72 * feel,
            static=True,
        )

        # Connected map routes use one shared mesh each, rather than growing
        # the physical entity/render pools with a node per paving segment.
        for kind in ("SETTLEMENT_ROADS", "SETTLEMENT_FENCES"):
            self._spawn_entity_locked(kind,0,0,0,(1,1,1),"#b69265",0,static=True)
        for fixture in settlement_contract.catalog()["fixtures"]:
            x,z=fixture["x"]*layout,fixture["z"]*layout
            scale=tuple(fixture["scale"])
            slot=self._spawn_entity_locked(fixture["kind"],x,self._terrain_height_locked(x,z)+scale[1],z,
                                           scale,"#c99b65",0,static=True)
            if slot is not None:self._yaw[slot]=math.radians(fixture.get("yaw",0))

        npc_spawns = npc_contract.spawns_from_content(self._content)
        for spawn in npc_spawns:
            placed = dict(spawn)
            placed["x"] = float(placed.get("x", 0.0)) * layout
            placed["z"] = float(placed.get("z", 0.0)) * layout
            self._spawn_npc_locked(placed)

        if self._stress:
            stress_start = 1 + 32 + len(npc_spawns)
            for index in range(stress_start, 480):
                angle = index * 0.37
                radius = (12.0 + float(index % 23) * 0.42) * layout
                scale = (
                    0.18 + (index % 3) * 0.04,
                    0.18 + (index % 4) * 0.03,
                    0.18 + (index % 2) * 0.05,
                )
                self._spawn_entity_locked(
                    "STRESS_PROP",
                    math.sin(angle) * radius,
                    self._terrain_height_locked(
                        math.sin(angle) * radius,
                        math.cos(angle) * radius,
                    ) + scale[1],
                    math.cos(angle) * radius,
                    scale,
                    "#b6a6c8" if index % 2 else "#c98989",
                    0.25,
                )

        self._append_event_locked(
            "WORLD_RESET",
            "Scene rebuilt from deterministic seed.",
        )

    def _append_event_locked(
        self,
        kind: str,
        text: str,
        *,
        actor_id: str = "system",
        subject_id: str = "",
        target_id: str = "",
        payload: Any = None,
    ) -> dict[str, Any]:
        event = events_contract.append(
            self._event_journal,
            kind,
            tick=self._tick,
            sim_time=self._sim_time,
            actor_id=actor_id,
            subject_id=subject_id,
            target_id=target_id,
            text=text,
            payload=payload,
        )
        self._events.append(
            {
                "tick": int(self._tick),
                "kind": str(kind),
                "text": str(text),
            }
        )
        self._events = self._events[-24:]
        from backend.game_engine_adapter_feedback import observe
        observe(self,event)
        self._animate_world_event_locked(kind, actor_id, subject_id, target_id, payload)
        return event

    def _next_item_instance_id_locked(self, prefix: str = "runtime-item") -> str:
        if getattr(self,'_local_character_id',''):
            # The local profile can relinquish an item to another profile or
            # escrow. A counter reconstructed from only live rows cannot then
            # prove a new identity across login, consumption, or transfer.
            from uuid import uuid4
            while True:
                self._item_counter += 1
                key=f"{str(prefix or 'runtime-item')[:31]}-{uuid4().hex}"
                if key not in self._item_instances:return key
        while True:
            self._item_counter += 1
            key=f"{str(prefix or 'runtime-item')[:32]}-{self._item_counter:04d}"
            if key not in self._item_instances:return key

    def _materialize_npc_item_instances_locked(self) -> None:
        """Reconcile durable NPC item refs with real carried instances."""
        people = self._individual_state.get("individuals", {})
        if not isinstance(people, dict):
            return
        for identity_id in sorted(people):
            person = people.get(identity_id)
            if not isinstance(person, dict):
                continue
            claimed: set[str] = set()
            for field, location in (("inventory", "POCKET"), ("equipment", "EQUIPPED")):
                references = person.get(field, [])
                if not isinstance(references, list):
                    continue
                reference_limit = (
                    identity_contract.MAX_EQUIPPED_ITEMS
                    if field == "equipment"
                    else identity_contract.MAX_CARRIED_ITEMS
                )
                for ordinal, raw_definition_id in enumerate(references[:reference_limit]):
                    definition_id = str(raw_definition_id or "")[:96]
                    if not definition_id or item_state.definition(self._item_catalog, definition_id) is None:
                        continue
                    existing = next(
                        (
                            row
                            for row in self._item_instances.values()
                            if isinstance(row, dict)
                            and str(row.get("instance_id", "")) not in claimed
                            and str(row.get("owner_id", "")) == str(identity_id)
                            and str(row.get("definition_id", "")) == definition_id
                            and str(row.get("location", "")) == location
                        ),
                        None,
                    )
                    if isinstance(existing, dict):
                        claimed.add(str(existing.get("instance_id", "")))
                        continue
                    if len(self._item_instances) >= item_state.MAX_WORLD_INSTANCES:
                        continue
                    context = "pocket" if location == "POCKET" else "equipped"
                    instance_id = f"npc-{identity_id}-{context}-{ordinal:02d}"[:64]
                    suffix = 0
                    while instance_id in self._item_instances:
                        suffix += 1
                        instance_id = f"npc-{identity_id}-{context}-{ordinal:02d}-{suffix}"[:64]
                    self._item_instances[instance_id] = item_state.make_instance(
                        self._item_catalog,
                        instance_id,
                        definition_id,
                        location=location,
                        owner_id=str(identity_id),
                        visual_phase=(sum(ord(char) for char in instance_id) % 100) / 17.0,
                    )
                    claimed.add(instance_id)
            # A saved or externally edited identity can remove a reference
            # without removing its old instance.  The identity table is the
            # authority for ownership, so discard only unreferenced carried
            # rows for this NPC; world/player rows are never touched here.
            for instance_id, row in list(self._item_instances.items()):
                if (
                    isinstance(row, dict)
                    and str(row.get("owner_id", "")) == str(identity_id)
                    and str(row.get("location", "")) in {"POCKET", "EQUIPPED"}
                    and str(instance_id) not in claimed
                ):
                    self._item_instances.pop(str(instance_id), None)

    def _seed_active_pack_world_items_locked(self) -> list[dict[str, Any]]:
        """Materialize authored pack drops as real ground item instances."""
        rows = self._content.get("initial_world_items", [])
        if not isinstance(rows, list):
            return []
        created: list[dict[str, Any]] = []
        existing_origins = {
            str(row.get("origin_id", ""))
            for row in self._item_instances.values()
            if isinstance(row, dict) and row.get("origin_id")
        }
        for raw in rows[: item_state.MAX_WORLD_INSTANCES]:
            if not isinstance(raw, dict) or not raw.get("id"):
                continue
            origin_id = str(raw.get("id"))[:64]
            if origin_id in existing_origins or len(self._item_instances) >= item_state.MAX_WORLD_INSTANCES:
                continue
            definition_id = str(raw.get("definition_id", ""))[:96]
            if item_state.definition(self._item_catalog, definition_id) is None:
                continue
            x = _clamp(raw.get("x"), -1000000.0, 1000000.0) * world.ISLAND_LAYOUT_SCALE
            z = _clamp(raw.get("z"), -1000000.0, 1000000.0) * world.ISLAND_LAYOUT_SCALE
            instance_id = f"pack-world-{origin_id}"[:64]
            if instance_id in self._item_instances:
                continue
            instance = item_state.make_instance(
                self._item_catalog,
                instance_id,
                definition_id,
                location="GROUND",
                quantity=max(1, _safe_int(raw.get("quantity"), 1)),
                position={
                    "x": x,
                    "y": self._terrain_height_locked(x, z),
                    "z": z,
                },
                visual_phase=(sum(ord(char) for char in instance_id) % 100) / 17.0,
            )
            instance["origin"] = "CONTENT_PACK"
            instance["origin_id"] = origin_id
            self._item_instances[instance_id] = instance
            existing_origins.add(origin_id)
            created.append(instance)
        return created

    def _rebuild_content_runtime_locked(self) -> None:
        """Rebind data tables after a page merge while preserving runtime rows."""
        self._set_life_spawns_locked(life_contract.spawns_from_content(self._content))
        self._item_catalog = item_state.catalog_from_content(self._content)
        self._gear_tables = gear_contract.tables_from_content(self._content)
        self._people_catalog = identity_contract.catalog_from_content(self._content)
        self._quest_catalog = quests_contract.normalized_catalog(
            self._content.get("quests")
        )
        self._dialogue_catalog = dialogue_contract.normalized_catalog(
            self._content.get("dialogue")
        )
        self._vendor_catalog = economy_contract.catalog_from_content(self._content)
        self._world_event_catalog = world_events_contract.normalized_catalog(
            self._content.get("world_events")
        )
        self._asset_catalog = assets_contract.extend_static_items(
            assets_contract.default_catalog(),
            self._content.get("asset_bindings"),
        )

        normalized_items: dict[str, dict[str, Any]] = {}
        for instance_id, raw in list(self._item_instances.items())[: item_state.MAX_WORLD_INSTANCES]:
            normalized = item_state.normalize_instance(self._item_catalog, raw)
            if normalized is not None:
                normalized_items[str(instance_id)] = normalized
        self._item_instances = normalized_items
        self._individual_state = identity_contract.restore_state(
            self._individual_state,
            self._people_catalog,
        )
        self._faction_state = factions_contract.normalize_state(
            self._faction_state,
            self._people_catalog.values(),
        )
        self._quest_state = quests_contract.normalize_state(
            self._quest_state,
            self._quest_catalog,
        )
        self._dialogue_state = dialogue_contract.normalize_state(self._dialogue_state)
        self._social_state = social_contract.normalize_state(self._social_state)
        self._world_event_state = world_events_contract.normalize_state(
            self._world_event_state,
            self._world_event_catalog,
        )
        self._economy_state = economy_contract.restore_state(
            self._economy_state,
            self._vendor_catalog,
        )
        profession_rows = copy.deepcopy(self._gear_tables.get("professions", {}))
        if isinstance(self._profession_state, dict):
            for profession_id, value in self._profession_state.items():
                if profession_id in profession_rows and isinstance(value, dict):
                    profession_rows[profession_id] = copy.deepcopy(value)
        self._profession_state = profession_rows
        self._seed_active_pack_world_items_locked()
        self._materialize_npc_item_instances_locked()
        self._refresh_all_npc_progression_locked()
        self._sync_npc_combat_presence_locked()

        existing_ids = {
            str(self._npc_ids[index])
            for index in self._npc_indices
            if self._alive[index] and self._npc_ids[index]
        }
        for spawn in npc_contract.spawns_from_content(self._content):
            identity_id = str(spawn.get("id", ""))
            if identity_id in existing_ids:
                continue
            if self._spawn_npc_locked(dict(spawn)) is not None:
                existing_ids.add(identity_id)

    def activate_content_pack(self, pack_id: str = "pack.tidefall-frontier") -> dict[str, Any]:
        """Activate one local content page without resetting the simulation."""
        wanted = str(pack_id or "pack.tidefall-frontier").strip()[:64]
        with self._lock:
            if wanted not in self._available_content_packs:
                snapshot = self.snapshot_locked()
                snapshot["error"] = "CONTENT_PACK_UNKNOWN"
                snapshot["content_pack_result"] = {
                    "error": snapshot["error"],
                    "pack_id": wanted,
                    "available": sorted(self._available_content_packs),
                }
                return snapshot
            if wanted in self._active_content_pack_ids:
                snapshot = self.snapshot_locked()
                snapshot["content_pack_result"] = {
                    "error": "CONTENT_PACK_ALREADY_ACTIVE",
                    "pack_id": wanted,
                    "active": list(self._active_content_pack_ids),
                }
                return snapshot
            before = {
                "content": self._content,
                "active": list(self._active_content_pack_ids),
                "item_catalog": self._item_catalog,
                "gear_tables": self._gear_tables,
                "people_catalog": self._people_catalog,
                "quest_catalog": self._quest_catalog,
                "dialogue_catalog": self._dialogue_catalog,
                "vendor_catalog": self._vendor_catalog,
                "world_event_catalog": self._world_event_catalog,
                "asset_catalog": self._asset_catalog,
                "items": self._item_instances,
                "people": self._individual_state,
                "factions": self._faction_state,
                "quests": self._quest_state,
                "dialogue": self._dialogue_state,
                "social": self._social_state,
                "world_events": self._world_event_state,
                "economy": self._economy_state,
                "professions": self._profession_state,
            }
            try:
                self._content = content_catalog.merge_content_pack(
                    self._content,
                    self._available_content_packs[wanted],
                )
                self._active_content_pack_ids.append(wanted)
                self._rebuild_content_runtime_locked()
            except (TypeError, ValueError, KeyError, OverflowError):
                self._content = before["content"]
                self._active_content_pack_ids = before["active"]
                self._item_catalog = before["item_catalog"]
                self._gear_tables = before["gear_tables"]
                self._people_catalog = before["people_catalog"]
                self._quest_catalog = before["quest_catalog"]
                self._dialogue_catalog = before["dialogue_catalog"]
                self._vendor_catalog = before["vendor_catalog"]
                self._world_event_catalog = before["world_event_catalog"]
                self._asset_catalog = before["asset_catalog"]
                self._item_instances = before["items"]
                self._individual_state = before["people"]
                self._faction_state = before["factions"]
                self._quest_state = before["quests"]
                self._dialogue_state = before["dialogue"]
                self._social_state = before["social"]
                self._world_event_state = before["world_events"]
                self._economy_state = before["economy"]
                self._profession_state = before["professions"]
                snapshot = self.snapshot_locked()
                snapshot["error"] = "CONTENT_PACK_ATOMIC_ROLLBACK"
                snapshot["content_pack_result"] = {
                    "error": snapshot["error"],
                    "pack_id": wanted,
                }
                return snapshot
            pack = self._available_content_packs[wanted]
            created = self._seed_active_pack_world_items_locked()
            if not created:
                seeded_ids = {
                    str(row.get("id", ""))
                    for row in pack.get("initial_world_items", [])
                    if isinstance(row, dict) and row.get("id")
                }
                created = [
                    row
                    for row in self._item_instances.values()
                    if isinstance(row, dict)
                    and str(row.get("origin_id", "")) in seeded_ids
                ]
            self._append_event_locked(
                "CONTENT_PACK_ACTIVATED",
                f"Activated authored content page {pack.get('name', wanted)}.",
                actor_id="system",
                subject_id=wanted,
                payload={
                    "pack_id": wanted,
                    "item_definitions": len(pack.get("items", {})),
                    "individuals": len(pack.get("npc_individuals", {})),
                    "npc_spawns": len(pack.get("npc_spawns", [])),
                    "world_items_created": len(created),
                },
            )
            snapshot = self.snapshot_locked()
            snapshot["content_pack_result"] = {
                "ok": True,
                "pack_id": wanted,
                "name": str(pack.get("name", wanted)),
                "created_world_items": [
                    str(row.get("instance_id", "")) for row in created
                ],
                "active": list(self._active_content_pack_ids),
            }
            return snapshot

    def _npc_owned_instance_locked(
        self,
        identity_id: str,
        definition_id: str = "",
        *,
        locations: set[str] | None = None,
    ) -> dict[str, Any] | None:
        allowed = locations or {"POCKET", "EQUIPPED"}
        candidates = [
            row
            for row in self._item_instances.values()
            if isinstance(row, dict)
            and str(row.get("owner_id", "")) == str(identity_id)
            and str(row.get("location", "")) in allowed
            and (not definition_id or str(row.get("definition_id", "")) == str(definition_id))
        ]
        candidates.sort(key=lambda row: str(row.get("instance_id", "")))
        return candidates[0] if candidates else None

    def _npc_remove_inventory_ref_locked(
        self,
        person: dict[str, Any],
        definition_id: str,
    ) -> bool:
        inventory = person.get("inventory")
        if not isinstance(inventory, list):
            return False
        for index, value in enumerate(inventory):
            if str(value) == str(definition_id):
                inventory.pop(index)
                person["inventory"] = inventory
                return True
        return False

    def _npc_remove_owned_instance_locked(
        self,
        identity_id: str,
        definition_id: str,
    ) -> bool:
        instance = self._npc_owned_instance_locked(identity_id, definition_id)
        if not isinstance(instance, dict):
            return False
        quantity = max(1, int(instance.get("quantity", 1)))
        if quantity > 1:
            instance["quantity"] = quantity - 1
        else:
            self._item_instances.pop(str(instance.get("instance_id", "")), None)
        return True

    def _npc_add_item_instance_locked(
        self,
        identity_id: str,
        definition_id: str,
        *,
        location: str = "POCKET",
    ) -> dict[str, Any] | None:
        if len(self._item_instances) >= item_state.MAX_WORLD_INSTANCES:
            return None
        if item_state.definition(self._item_catalog, definition_id) is None:
            return None
        prefix = "pocket" if location == "POCKET" else "equipped"
        instance_id = self._next_item_instance_id_locked(f"npc-{identity_id}-{prefix}")
        while instance_id in self._item_instances:
            instance_id = self._next_item_instance_id_locked(f"npc-{identity_id}-{prefix}")
        instance = item_state.make_instance(
            self._item_catalog,
            instance_id,
            definition_id,
            location=location,
            owner_id=identity_id,
            visual_phase=(self._item_counter % 17) * 0.31,
        )
        self._item_instances[instance_id] = instance
        return instance

    def _npc_equipped_instances_locked(self, identity_id: str) -> list[dict[str, Any]]:
        """Return the canonical gear rows currently equipped by one NPC."""
        rows = [
            row
            for row in self._item_instances.values()
            if isinstance(row, dict)
            and str(row.get("owner_id", "")) == str(identity_id)
            and str(row.get("location", "")) == "EQUIPPED"
            and isinstance(row.get("gear"), dict)
        ]
        rows.sort(key=lambda row: str(row.get("instance_id", "")))
        return rows[: identity_contract.MAX_EQUIPPED_ITEMS]

    def _refresh_npc_progression_locked(
        self,
        identity_id: str,
        person: dict[str, Any] | None = None,
        *,
        source: str = "RECALCULATE",
    ) -> dict[str, Any]:
        """Recompute one NPC's derived power from its actual equipped rows."""
        people = self._individual_state.get("individuals", {})
        resolved = person if isinstance(person, dict) else (
            people.get(str(identity_id)) if isinstance(people, dict) else None
        )
        if not isinstance(resolved, dict):
            return {"changed": False, "error": "NPC_IDENTITY_NOT_FOUND"}
        state = resolved.get("progression")
        if not isinstance(state, dict):
            state = npc_progression.starter_state(
                identity_id,
                role=resolved.get("role"),
                archetype=resolved.get("archetype"),
                occupation=resolved.get("occupation"),
            )
            resolved["progression"] = state
        result = npc_progression.recalculate(
            state,
            self._npc_equipped_instances_locked(identity_id),
            source=source,
            sim_time=self._sim_time,
        )
        if result.get("changed"):
            resolved["revision"] = max(0, int(resolved.get("revision", 0))) + 1
        return result

    def _refresh_all_npc_progression_locked(self) -> None:
        people = self._individual_state.get("individuals", {})
        if not isinstance(people, dict):
            return
        for identity_id in sorted(people):
            person = people.get(identity_id)
            if isinstance(person, dict):
                self._refresh_npc_progression_locked(
                    str(identity_id),
                    person,
                    source="STATE_BIND",
                )

    def _player_equipped_instances_locked(self) -> list[dict[str, Any]]:
        rows = [
            row
            for row in self._item_instances.values()
            if isinstance(row, dict)
            and str(row.get("owner_id", "")) == "player"
            and str(row.get("location", "")) == "EQUIPPED"
            and isinstance(row.get("gear"), dict)
        ]
        rows.sort(key=lambda row: str(row.get("instance_id", "")))
        return rows[: item_state.MAX_EQUIPPED_ITEMS]

    def _start_character_action_locked(self, actor_id: Any, clip: Any) -> int:
        identity = str(actor_id or "").strip() or "player"
        name = str(clip or "").strip()
        duration = animation_contract.ACTION_CLIP_SECONDS.get(name)
        if duration is None:
            return 0
        if name != "Death" and not self._combat_state.get("actors", {}).get(identity, {}).get("alive", True) and not (identity=='player' and self._is_ghost_locked()):
            return 0
        self._character_action_serial = (self._character_action_serial + 1) % 2_000_000_000
        self._character_actions[identity] = {
            "clip": name,
            "until": self._sim_time + duration,
            "serial": self._character_action_serial,
        }
        if identity != "player" and name in animation_contract.WORLD_INTERACTION_CLIPS:
            index = self._npc_index_for_id_locked(identity)
            if index is not None:
                self._vx[index] = self._vz[index] = 0.
        return self._character_action_serial

    def _gather_animation_clip_locked(self, definition_id: str) -> str:
        definition = item_state.definition(self._item_catalog, definition_id) or {}
        tags = {str(tag).upper() for tag in definition.get("tags", [])}
        name = str(definition_id).lower()
        # Loose produce, ore and logs are picked up. Harvesting a live
        # plant uses the distinct, authoritative NATURE_INTERACTION event.
        if tags.intersection({"HERB", "PLANT", "FIBER", "FLOWER"}) or any(
                part in name for part in ("herb", "flower", "fiber", "mushroom")):
            return "Gather"
        return "Pickup"

    @staticmethod
    def _craft_animation_clip(profession: Any, station_id: Any = "") -> str:
        name = (str(profession) + ":" + str(station_id)).upper()
        if "ENCHANT" in name:
            return "Enchant"
        if "COOK" in name or "CAMPFIRE" in name:
            return "Cook"
        return "Craft"

    def _animate_world_event_locked(self, kind, actor_id, subject_id, target_id, payload):
        """Observe committed interactions, including NPCs acting independently.

        Failed attempts never animate. This affects poses only, after the real
        inventory/dialogue transaction has succeeded.
        """
        data = payload if isinstance(payload, dict) else {}
        identity = str(actor_id)
        clip = ""
        tool = ""
        if kind == "ITEM_PICKUP":
            clip = self._gather_animation_clip_locked(str(data.get("definition_id", "")))
        elif kind == "CONTAINER_OPEN":
            clip = "OpenChest"
        elif kind == "CONTAINER_LOOT" and int(data.get("count", 0)) > 0:
            clip = "Pickup"
        elif kind in {"GEAR_ENCHANT", "ENCHANT"}:
            clip = "Enchant"
            if identity == "system":
                identity = "player"
        elif kind in {"CRAFT", "GEAR_CRAFT"}:
            recipe = self._gear_tables.get("recipes", {}).get(str(subject_id), {})
            clip = self._craft_animation_clip(recipe.get("profession", "COOKING" if kind == "CRAFT" else ""), target_id)
            if clip == "Craft":
                tool = "hammer"
        elif kind in {"DIALOGUE_START", "DIALOGUE_CHOICE"}:
            clip = "Talk"
            self._start_character_action_locked(target_id, clip)
        elif kind == "NPC_SOCIAL" and data.get("outcome") == "CONVERSATION":
            clip = "Talk"
            self._start_character_action_locked(target_id, clip)
        elif kind == "NATURE_INTERACTION":
            action = str(data.get("action", "")).upper()
            species = str(data.get("species", ""))
            clip = {"CLIP": "Gather", "LOOT": "Pickup", "SKIN": "Gather", "BRUSH": "Pet",
                    "PET": "Pet", "FISH": "FishCast", "CATCH": "NetCatch",
                    "MILK": "Milk", "SHEAR": "Shear"}.get(action, "")
            if action == "PICK":
                clip = "HarvestFruit" if species in {"coconut", "banana", "apple", "grapes", "grape_vine"} else "Gather"
            elif action == "ATTACK":
                clip = self._player_attack_animation_clip_locked()
            tool = {"CLIP": "shears", "SKIN": "knife", "BRUSH": "brush", "FISH": "rod",
                    "CATCH": "net", "SHEAR": "shears"}.get(action, "")
        elif kind == "NPC_WORLD_ACTION" and str(data.get("status", "")) not in {"BLOCKED", "FAILED"}:
            action = str(subject_id).upper()
            if action in {"GATHER", "HAUL", "INSPECT_LOOT", "SEEK_GEAR"} and str(data.get("status", "")) in {"COMMITTED", "LOOTED", "INSPECTED", "EQUIPPED"}:
                clip = self._gather_animation_clip_locked(str(data.get("definition_id", "")))
            elif action == "CRAFT":
                clip = self._craft_animation_clip(data.get("profession", ""), target_id)
                if clip == "Craft":
                    tool = "hammer"
            elif action == "SEEK_FOOD" and data.get("status") == "CONSUMED":
                clip = "Eat"
            elif action == "SEEK_WATER" and data.get("status") == "REFILLED":
                clip = "Drink"
        if clip and identity not in {"", "system"}:
            self._start_character_action_locked(identity, clip)
            if tool and self._character_actions.get(identity, {}).get("clip") == clip:
                self._character_actions[identity]["tool"] = tool

    def _character_action_for_locked(self, actor_id: Any) -> dict[str, Any]:
        identity = str(actor_id or "").strip()
        entry = self._character_actions.get(identity)
        if not isinstance(entry, dict):
            return {}
        if (entry.get("clip") == "Death"
                and not self._combat_state.get("actors", {}).get(identity, {}).get("alive", True)
                and not (identity=='player' and self._is_ghost_locked())):
            # Keep the terminal pose until the real simulation respawn.
            return entry
        if float(entry.get("until", 0.0)) <= self._sim_time:
            self._character_actions.pop(identity, None)
            return {}
        return entry

    def _decorate_character_animation_locked(self, animation: Any, actor_id: Any) -> str:
        if not isinstance(animation, dict):
            return ""
        entry = self._character_action_for_locked(actor_id)
        clip = str(entry.get("clip", ""))
        if clip in animation_contract.WORLD_INTERACTION_CLIPS and (
                float(animation.get("speed_mps", 0.0)) > .8
                or animation.get("locomotion") in {"AIR", "DOUBLE_JUMP", "FLY", "SWIM", "HOVERBOARD", "HOVERBOARD_AIR", "BOAT", "GRAPPLE"}):
            # Full-body work has planted feet. Moving or jumping interrupts
            # that visual action rather than sliding the working pose around.
            self._character_actions.pop(str(actor_id), None)
            entry, clip = {}, ""
        if not self._combat_state.get("actors", {}).get(str(actor_id), {}).get("alive", True) and not (str(actor_id)=='player' and self._is_ghost_locked()):
            clip = "Death"
        animation["action"] = clip
        animation["action_serial"] = int(entry.get("serial", 0)) if clip else 0
        animation["world_interaction"] = clip in animation_contract.WORLD_INTERACTION_CLIPS
        animation["interaction_tool"] = str(entry.get("tool", "")) if animation["world_interaction"] else ""
        if clip:
            # Combat actions keep their authored one-shot timing instead of
            # inheriting the current walk cadence.
            animation["cadence_hz"] = 0.0
        elif str(actor_id)=='player' and animation.get('locomotion') in {'IDLE','WALK','SPRINT'}:
            main=next((row for row in self._player_equipped_instances_locked()
                       if row.get('equipped_slot')=='MAIN_HAND'),None)
            if main and main.get('definition_id')=='item.weapon_sword' and item_state.equipment_wielding(main)=='2H':
                return {'IDLE':'TwoHandIdle','WALK':'TwoHandWalk','SPRINT':'TwoHandSprint'}[animation['locomotion']]
        return clip

    def _player_attack_animation_clip_locked(self, action_id: Any = "") -> str:
        action = str(action_id or "").strip().lower().replace("-", "_")
        if "parry" in action or "block" in action:
            return "Parry"
        if "dodge_left" in action or "evade_left" in action:
            return "DodgeLeft"
        if "dodge" in action or "evade" in action:
            return "DodgeRight"
        if "shield_bash" in action:
            return "ShieldBash"
        if "reload" in action:
            return "Reload"

        weapons = [
            row for row in self._player_equipped_instances_locked()
            if (str(row.get("definition_id", "")).startswith("item.weapon_")
                or row.get("definition_id") == "item.iron_saber")
            and str(row.get("equipped_slot", "")) in {"MAIN_HAND", "OFF_HAND"}
        ]
        pistols = [row for row in weapons if row.get("definition_id") == "item.weapon_pistol"]
        if pistols:
            if len(pistols) > 1:
                return "DualPistolFire"
            spec = firearms_contract.profile(str(pistols[0].get("instance_id", "")))
            subtype = str(spec.get("weapon_subtype", "pistol"))
            return "ShotgunFire" if subtype == "shotgun" else (
                "RifleFire" if subtype in {"rifle", "gatling", "railgun", "launcher", "cannon"}
                else "PistolFire"
            )

        main = next((row for row in weapons if row.get("equipped_slot") == "MAIN_HAND"), None)
        if main is None:
            return "UnarmedAttack"
        if main.get("definition_id") == "item.iron_saber":
            return "OneHandSlash"
        family = str(main.get("definition_id", "")).removeprefix("item.weapon_")
        variant = item_state.item_appearance_index(main.get("instance_id", ""))
        if family == "wand":
            return "WandCast"
        if family == "staff":
            return "StaffCast"
        if family == "mace":
            from backend.game_engine_caster_designs import design
            construction = str(design("mace", variant).get("construction", ""))
            if construction == "flail":
                return "FlailSwing"
            if "scythe" in construction:
                return "ScytheSweep"
            return "TwoHandOverhead" if item_state.equipment_wielding(main) == "2H" else "OneHandOverhead"
        if family == "axe":
            from backend.game_engine_shield_axe_designs import AXES
            row = AXES[variant]
            construction = str(row[2]).lower()
            if "scythe" in construction:
                return "ScytheSweep"
            return "TwoHandOverhead" if str(row[-1]) == "2H" else "OneHandSlash"
        if family == "sword":
            from backend.game_engine_sword_designs import SWORDS
            name = str(SWORDS[variant][0]).lower()
            if any(token in name for token in ("rapier", "estoc", "stiletto", "stilet", "dirk", "stinger")):
                return "OneHandThrust"
            if any(token in name for token in ("zweihander", "nodachi", "claymore", "longsword", "flamberge")):
                return "TwoHandSlash"
            return "OneHandSlash"
        if family == "spear":
            return "SpearThrust"
        if family == "bow":
            return "BowShot"
        if family == "whip":
            return "WhipCrack"
        if family == "boomerang":
            return "BoomerangThrow"
        if family == "shield":
            return "ShieldBash"
        if item_state.equipment_wielding(main) == "2H":
            return "TwoHandOverhead"
        return "OneHandSlash"

    def _player_combat_profile_locked(self) -> dict[str, Any]:
        """Derive player combat stats from progression and real equipped gear."""
        temporary = copy.deepcopy(self._progression)
        gear_stats: dict[str, float] = {}
        for item in self._player_equipped_instances_locked():
            if float(item.get('condition',1.))<=0.:continue
            gear = item.get("gear", {})
            stats = gear.get("stats", {}) if isinstance(gear, dict) else {}
            if isinstance(stats, dict):
                for key, value in stats.items():
                    key_name = str(key).strip().lower()
                    if not key_name:
                        continue
                    try:
                        gear_stats[key_name] = gear_stats.get(key_name, 0.0) + float(value)
                    except (TypeError, ValueError, OverflowError):
                        continue
            for affix in item.get("affixes", [])[:4] if isinstance(item.get("affixes"), list) else []:
                if not isinstance(affix, dict):
                    continue
                key_name = str(affix.get("stat", "")).strip().lower()
                if key_name:
                    try:
                        gear_stats[key_name] = gear_stats.get(key_name, 0.0) + float(affix.get("value", 0.0))
                    except (TypeError, ValueError, OverflowError):
                        continue
        temporary["gear_stats"] = gear_stats
        for key,value in self._item_set_stats_locked(self._player_equipped_instances_locked()).items():
            gear_stats[key]=gear_stats.get(key,0.)+value
        gear_stats['armor']=gear_stats.get('armor',0.)+self._spell_armor_bonus_locked()
        temporary["enchant_effects"] = enchant_contract.equipped_effects(
            [i for i in self._player_equipped_instances_locked() if float(i.get('condition',1.))>0.], int(temporary.get("level", 1)))
        temporary["derived_stats"] = {}
        profile = combat_contract.profile(
            temporary,
            kind="PLAYER",
            actor_id="player",
            role=str(temporary.get("spec", "EXPLORER")),
        )
        if getattr(self,'_services',{}).get('sickness_until',0.) > time.time():
            for key in ('max_health','damage','armor'):profile[key] = max(1.,profile[key]*.25)
        return profile

    def _npc_index_for_id_locked(self, identity_id: Any) -> int | None:
        wanted = str(identity_id or "")
        for index in self._npc_indices:
            actor = self._combat_state.get("actors", {}).get(self._npc_ids[index])
            if (
                self._alive[index]
                and str(self._npc_ids[index]) == wanted
                and not (isinstance(actor, dict) and not actor.get("alive", True))
            ):
                return index
        return None

    def _npc_combat_profile_locked(
        self,
        identity_id: str,
        person: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        people = self._individual_state.get("individuals", {})
        resolved = person if isinstance(person, dict) else (
            people.get(identity_id) if isinstance(people, dict) else None
        )
        if not isinstance(resolved, dict):
            state = npc_progression.starter_state(identity_id)
            return combat_contract.profile(state, kind="NPC", actor_id=identity_id)
        state = resolved.get("progression")
        if not isinstance(state, dict):
            state = npc_progression.starter_state(
                identity_id,
                role=resolved.get("role"),
                archetype=resolved.get("archetype"),
                occupation=resolved.get("occupation"),
            )
            resolved["progression"] = state
        return combat_contract.profile(
            state,
            kind="NPC",
            actor_id=identity_id,
            role=str(resolved.get("role", "")),
            gear_bonus=self._item_set_stats_locked(self._npc_equipped_instances_locked(identity_id),resolved.get('professions',{})),
        )

    def _ensure_combat_actors_locked(self) -> None:
        player_profile = self._player_combat_profile_locked()
        combat_contract.ensure_actor(self._combat_state, "player", player_profile)
        for index in self._npc_indices[: npc_contract.MAX_NPCS]:
            if not self._alive[index] or not self._npc_ids[index]:
                continue
            identity_id = str(self._npc_ids[index])
            profile = self._npc_combat_profile_locked(identity_id)
            combat_contract.ensure_actor(self._combat_state, identity_id, profile)

    def _sync_npc_combat_presence_locked(self) -> None:
        """Keep the physical NPC row aligned with durable combat defeat state."""
        actors = self._combat_state.get("actors", {})
        if not isinstance(actors, dict):
            return
        for index in self._npc_indices[: npc_contract.MAX_NPCS]:
            identity_id = str(self._npc_ids[index] or "")
            actor = actors.get(identity_id)
            if not identity_id or not isinstance(actor, dict):
                continue
            if not actor.get("alive", True):
                self._vx[index] = 0.0
                self._vz[index] = 0.0
                self._npc_state[index] = "DEAD"
                self._npc_reason[index] = "COMBAT_DEFEATED"

    def _record_quest_event_locked(self, event: dict[str, Any]) -> dict[str, Any]:
        self._party_quest_credit_locked(event)
        result = quests_contract.record_event(
            self._quest_state,
            self._quest_catalog,
            event,
            self._sim_time,
        )
        if result.get("changed"):
            for progress_row in result.get("quests", [])[: quests_contract.MAX_ACTIVE]:
                if not isinstance(progress_row, dict):
                    continue
                status = str(progress_row.get("status", "ACTIVE")).upper()
                self._append_event_locked(
                    "QUEST_READY" if status == "READY" else "QUEST_PROGRESS",
                    f"Quest {progress_row.get('quest_id', '')} is {status.lower()}.",
                    actor_id="player",
                    subject_id=str(progress_row.get("quest_id", "")),
                    payload=copy.deepcopy(progress_row),
                )
        return result

    def _tick_landmark_visits_locked(self) -> None:
        """Record one visit when an active exploration quest is entered."""
        active = self._quest_state.get("active", {})
        if not isinstance(active, dict) or not active:
            self._quest_visit_presence = set()
            return

        current_presence: set[str] = set()
        for quest_id, progress in list(active.items())[: quests_contract.MAX_ACTIVE]:
            definition = self._quest_catalog.get(str(quest_id))
            objective = definition.get("objective", {}) if isinstance(definition, dict) else {}
            location = objective.get("location", {}) if isinstance(objective, dict) else {}
            if (
                not isinstance(progress, dict)
                or str(progress.get("status", "ACTIVE")).upper() == "READY"
                or not isinstance(objective, dict)
                or str(objective.get("kind", "")).upper() != "VISIT"
                or not isinstance(location, dict)
                or "x" not in location
                or "z" not in location
            ):
                continue
            required_mode = str(objective.get("required_mode") or "").upper()
            if required_mode and required_mode != self._movement_mode:
                continue
            target_x = _clamp(location.get("x"), -100000.0, 100000.0)
            target_z = _clamp(location.get("z"), -100000.0, 100000.0)
            radius = _clamp(objective.get("radius_m"), 1.0, 64.0, 3.0)
            if math.hypot(self._x[0] - target_x, self._z[0] - target_z) > radius:
                continue

            wanted = str(quest_id)
            current_presence.add(wanted)
            if wanted in self._quest_visit_presence:
                continue
            self._record_quest_event_locked({
                "kind": "VISIT",
                "target_id": str(objective.get("target_id", "")),
                "movement_mode": self._movement_mode,
                "x": round(self._x[0], 3),
                "z": round(self._z[0], 3),
            })
        self._quest_visit_presence = current_presence

    def _spawn_combat_loot_locked(
        self,
        identity_id: str,
        index: int,
    ) -> dict[str, Any]:
        if len(self._item_instances) >= item_state.MAX_WORLD_INSTANCES:
            return {"created": False, "error": "ITEM_WORLD_BUDGET"}
        seed = (
            self._tick * 1103515245
            + sum((ordinal + 1) * ord(char) for ordinal, char in enumerate(identity_id))
            + max(0, int(index)) * 97
        ) & 0xFFFFFFFF
        rolled = item_state.roll_loot(self._item_catalog, seed, "loot.coastal_cache")
        definition_id = str(rolled.get("item_id", ""))
        if item_state.definition(self._item_catalog, definition_id) is None:
            return {"created": False, "error": "ITEM_DEFINITION_MISSING"}
        instance_id = self._next_item_instance_id_locked("combat-drop")
        while instance_id in self._item_instances:
            instance_id = self._next_item_instance_id_locked("combat-drop")
        position = {
            "x": self._x[index],
            "y": self._terrain_height_locked(self._x[index], self._z[index]),
            "z": self._z[index],
        }
        instance = item_state.make_instance(
            self._item_catalog,
            instance_id,
            definition_id,
            location="GROUND",
            quantity=max(1, int(rolled.get("quantity", 1))),
            position=position,
            visual_phase=(self._item_counter % 17) * 0.31,
        )
        affix_payload = content_catalog.deterministic_loot(
            self._content,
            seed,
            base_item_id=definition_id,
        )
        instance["seed"] = int(seed)
        instance["base_item_id"] = definition_id
        instance["roll_table_id"] = "loot.coastal_cache"
        instance["roll"] = max(0, int(rolled.get("roll", 0)))
        instance["origin"] = "COMBAT_DROP"
        instance['source_actor_id']=identity_id
        instance['loot_claimed']=False
        instance["affixes"] = copy.deepcopy(affix_payload.get("affixes", [])[:2])
        self._item_instances[instance_id] = instance
        return {
            "created": True,
            "instance_id": instance_id,
            "definition_id": definition_id,
            "rarity": str(instance.get("rarity", "COMMON")),
            "item": item_state.instance_view(
                self._item_catalog,
                instance,
                sim_time=self._sim_time,
            ),
        }

    def _handle_npc_defeat_locked(
        self,
        identity_id: str,
        index: int,
        attack_result: dict[str, Any],
    ) -> dict[str, Any]:
        people = self._individual_state.get("individuals", {})
        person = people.get(identity_id) if isinstance(people, dict) else None
        faction_result: dict[str, Any] = {}
        loot_result = self._spawn_combat_loot_locked(identity_id, index)
        xp_result = progression.grant_xp(
            self._progression,
            35 + max(1, int(self._npc_combat_profile_locked(identity_id).get("level", 1))) * 10,
        )
        self._last_xp_visual = dict(x=self._x[index],y=self._y[index]+.5,
            z=self._z[index],time_s=self._sim_time)
        if isinstance(person, dict):
            faction_result = factions_contract.adjust_person(
                self._faction_state,
                identity_id,
                -100,
                source="PLAYER_COMBAT",
                sim_time=self._sim_time,
            )
            person["relationship_to_player"] = round(
                _clamp(person.get("relationship_to_player"), -1.0, 1.0, 0.0) - 0.35,
                4,
            )
            identity_contract.record_memory(
                self._individual_state,
                identity_id,
                "PLAYER_ATTACK",
                "player",
                self._sim_time,
                text="The player defeated me; future encounters will remember this.",
                weight=1.0,
            )
        quest_result = self._record_quest_event_locked(
            {
                "kind": "DEFEAT",
                "target_id": identity_id,
                "amount": 1,
            }
        )
        self._vx[index] = 0.0
        self._vz[index] = 0.0
        self._npc_state[index] = "DEAD"
        self._npc_reason[index] = "COMBAT_DEFEATED"
        self._append_event_locked(
            "COMBAT_DEFEAT",
            f"{identity_id} was defeated; the world retained a real loot drop.",
            actor_id="player",
            subject_id="DEFEAT",
            target_id=identity_id,
            payload={
                "attack": copy.deepcopy(attack_result),
                "loot": copy.deepcopy(loot_result),
                "xp": copy.deepcopy(xp_result),
                "faction": copy.deepcopy(faction_result),
                "quest": copy.deepcopy(quest_result),
            },
        )
        return {
            "loot": loot_result,
            "xp": xp_result,
            "faction": faction_result,
            "quest": quest_result,
        }

    def _tick_combat_locked(self) -> None:
        """Run bounded NPC retaliation and respawn checks at a cheap cadence."""
        if self._tick % 3 != 0:
            return
        self._ensure_combat_actors_locked()
        for result in combat_contract.tick_statuses(self._combat_state, self._sim_time):
            if result.get("defeated"):
                if result["defender_id"] == "player":
                    self._vx[0] = self._vy[0] = self._vz[0] = 0.0
                elif result.get("attacker_id") == "player" or result.get('attacker_id') in self._services['group']['members'] or str(result.get('attacker_id','')).startswith('pet:'):
                    index = next((i for i in self._npc_indices
                                  if str(self._npc_ids[i]) == result["defender_id"]), None)
                    if index is not None:
                        result["defeat"] = self._handle_npc_defeat_locked(
                            result["defender_id"], index, result)
            self._last_combat = copy.deepcopy(result)
        player_profile = self._player_combat_profile_locked()
        player_actor = combat_contract.ensure_actor(
            self._combat_state,
            "player",
            player_profile,
        )
        self._tick_lifecycle_locked()
        if not player_actor.get("alive"):
            if not self._is_ghost_locked():self._vx[0] = self._vy[0] = self._vz[0] = 0.0
            return
        for index in list(self._npc_indices)[: npc_contract.MAX_NPCS]:
            if not self._alive[index] or not self._npc_ids[index]:
                continue
            identity_id = str(self._npc_ids[index])
            person = self._individual_state.get("individuals", {}).get(identity_id)
            npc_profile = self._npc_combat_profile_locked(identity_id, person)
            actor = combat_contract.ensure_actor(
                self._combat_state,
                identity_id,
                npc_profile,
            )
            if not actor.get("alive"):
                if self._instance_encounter_locked(identity_id):continue
                respawned = combat_contract.respawn_actor(
                    self._combat_state,
                    identity_id,
                    npc_profile,
                    self._sim_time,
                )
                if respawned is not None:
                    self._vx[index] = self._vy[index] = self._vz[index] = 0.0
                    self._x[index] = self._npc_home_x[index]
                    self._z[index] = self._npc_home_z[index]
                    self._y[index] = self._terrain_height_locked(
                        self._x[index], self._z[index]
                    ) + 0.65
                    self._npc_state[index] = "WANDER"
                    self._npc_reason[index] = "COMBAT_RESPAWN"
                    self._append_event_locked(
                        "NPC_COMBAT_RESPAWN",
                        f"{identity_id} returned to the world.",
                        actor_id=identity_id,
                        target_id=identity_id,
                    )
                continue
            if str(actor.get("engaged_target", "")) != "player":
                continue
            if identity_id in self._services['group']['members'] and not self._duel_opponent_locked(identity_id):
                actor['engaged_target']=''
                continue
            distance = math.hypot(self._x[index] - self._x[0], self._z[index] - self._z[0])
            if distance > min(3.25, float(npc_profile.get("attack_range_m", 2.5))) + 0.35:
                continue
            if not self._npc_line_of_sight_locked(index):
                continue
            result = combat_contract.resolve_attack(
                self._combat_state,
                attacker_id=identity_id,
                defender_id="player",
                attacker_profile=npc_profile,
                defender_profile=player_profile,
                sim_time=self._sim_time,
                seed=self._tick + index * 31,
                action_id="npc_retaliate",
            )
            if not result.get("ok"):
                continue
            self._start_character_action_locked(identity_id, "UnarmedAttack")
            self._start_character_action_locked(
                "player", "Death" if result.get("defeated") else "HitReact"
            )
            self._last_combat = copy.deepcopy(result)
            self._append_event_locked(
                "COMBAT_ATTACK",
                f"{identity_id} hit the player for {result.get('damage', 0)}.",
                actor_id=identity_id,
                subject_id="npc_retalitate",
                target_id="player",
                payload=copy.deepcopy(result),
            )
            if result.get("defeated"):
                self._append_event_locked(
                    "COMBAT_DEFEAT",
                    "The player was defeated. Release spirit or accept resurrection.",
                    actor_id=identity_id,
                    subject_id="DEFEAT",
                    target_id="player",
                    payload=copy.deepcopy(result),
                )
                self._vx[0] = self._vy[0] = self._vz[0] = 0.0

    @staticmethod
    def _npc_remove_equipment_ref_locked(
        person: dict[str, Any],
        definition_id: str,
    ) -> bool:
        equipment = person.get("equipment")
        if not isinstance(equipment, list):
            return False
        for index, value in enumerate(equipment):
            if str(value) == str(definition_id):
                equipment.pop(index)
                person["equipment"] = equipment
                return True
        return False

    @staticmethod
    def _npc_add_equipment_ref_locked(
        person: dict[str, Any],
        definition_id: str,
    ) -> bool:
        equipment = person.get("equipment")
        if not isinstance(equipment, list) or len(equipment) >= identity_contract.MAX_EQUIPPED_ITEMS:
            return False
        equipment.append(str(definition_id)[:96])
        person["equipment"] = equipment[: identity_contract.MAX_EQUIPPED_ITEMS]
        return True

    def _npc_equip_better_gear_locked(
        self,
        identity_id: str,
        person: dict[str, Any],
        candidate: dict[str, Any],
    ) -> tuple[bool, dict[str, Any]]:
        """Equip a pocket item only when its real score beats that slot."""
        if (
            not isinstance(candidate, dict)
            or str(candidate.get("owner_id", "")) != str(identity_id)
            or str(candidate.get("location", "")) != "POCKET"
            or not isinstance(candidate.get("gear"), dict)
        ):
            return False, {"reason": "CANDIDATE_NOT_NPC_POCKET_GEAR"}
        slot = str(
            candidate.get("equipped_slot")
            or candidate.get("gear", {}).get("slot", "")
        ).upper()
        if not slot:
            return False, {"reason": "GEAR_SLOT_MISSING"}
        equipped_rows = [
            row for row in self._npc_equipped_instances_locked(identity_id)
            if str(row.get("equipped_slot") or row.get("gear", {}).get("slot", "")).upper() == slot
        ]
        current = equipped_rows[0] if equipped_rows else None
        decision = npc_progression.compare_item(candidate, current)
        decision.update(
            {
                "slot": slot,
                "candidate_instance_id": str(candidate.get("instance_id", "")),
                "candidate_definition_id": str(candidate.get("definition_id", "")),
            }
        )
        if not decision.get("upgrade"):
            return False, decision

        person_backup = copy.deepcopy(person)
        instance_ids = [str(candidate.get("instance_id", ""))]
        if isinstance(current, dict):
            instance_ids.append(str(current.get("instance_id", "")))
        instance_backups = {
            instance_id: copy.deepcopy(self._item_instances[instance_id])
            for instance_id in instance_ids
            if instance_id in self._item_instances
        }

        def rollback() -> None:
            person.clear()
            person.update(person_backup)
            for instance_id, backup in instance_backups.items():
                row = self._item_instances.get(instance_id)
                if isinstance(row, dict):
                    row.clear()
                    row.update(copy.deepcopy(backup))

        candidate_definition_id = str(candidate.get("definition_id", ""))
        if not self._npc_remove_inventory_ref_locked(person, candidate_definition_id):
            return False, {**decision, "reason": "CANDIDATE_INVENTORY_REF_MISSING"}
        if isinstance(current, dict):
            current_definition_id = str(current.get("definition_id", ""))
            if not self._npc_remove_equipment_ref_locked(person, current_definition_id):
                rollback()
                return False, {**decision, "reason": "CURRENT_EQUIPMENT_REF_MISSING"}
            ok, transition = item_state.transition_instance(
                current,
                "POCKET",
                owner_id=identity_id,
            )
            if not ok or not self._npc_add_inventory_ref_locked(person, current_definition_id):
                rollback()
                return False, {**decision, "reason": transition.get("error", "CURRENT_GEAR_MOVE_FAILED")}
        ok, transition = item_state.transition_instance(
            candidate,
            "EQUIPPED",
            owner_id=identity_id,
            equipped_slot=slot,
        )
        if not ok or not self._npc_add_equipment_ref_locked(person, candidate_definition_id):
            rollback()
            return False, {**decision, "reason": transition.get("error", "CANDIDATE_GEAR_MOVE_FAILED")}
        return True, {
            **decision,
            "gear_upgrade": True,
            "previous_instance_id": str(current.get("instance_id", "")) if isinstance(current, dict) else "",
            "equipped_instance_id": str(candidate.get("instance_id", "")),
        }

    def _item_instance_locked(self, instance_id: Any) -> dict[str, Any] | None:
        wanted = str(instance_id or "")
        row = self._item_instances.get(wanted)
        return row if isinstance(row, dict) else None

    @staticmethod
    def _item_owned_state(location: Any, owner_id: Any) -> bool:
        return (
            str(owner_id or "") == "player"
            and str(location or "").upper() in item_state.PLAYER_OWNED_LOCATIONS
        )

    def _ensure_inventory_slots_locked(self) -> None:
        used: set[int] = set()
        pending: list[dict[str, Any]] = []
        for row in self._item_instances.values():
            if not isinstance(row, dict) or str(row.get("location")) != "INVENTORY" or str(row.get("owner_id")) != "player":
                continue
            index = _safe_int(row.get("slot_index"), -1)
            if 0 <= index < item_state.MAX_INVENTORY_SLOTS and index not in used:
                used.add(index)
                row["slot_index"] = index
            else:
                pending.append(row)
        free = (index for index in range(item_state.MAX_INVENTORY_SLOTS) if index not in used)
        for row in pending:
            row["slot_index"] = next(free, -1)

    def _move_item_locked(
        self,
        instance: dict[str, Any],
        location: str,
        *,
        owner_id: str | None = None,
        container_id: str | None = None,
        equipped_slot: str | None = None,
        position: dict[str, Any] | None = None,
    ) -> tuple[bool, dict[str, Any]]:
        if self._item_binding_locked(instance):return False,{'error':'ITEM_PENDING_CONFIRMATION'}
        if (
            str(location).upper() == "INVENTORY"
            and not (
                str(instance.get("location")) == "INVENTORY"
                and str(instance.get("owner_id")) == "player"
            )
            and sum(
                1 for row in self._item_instances.values()
                if isinstance(row, dict)
                and str(row.get("location")) == "INVENTORY"
                and str(row.get("owner_id")) == "player"
            ) >= item_state.MAX_INVENTORY_SLOTS
        ):
            return False, {"error": "ITEM_INVENTORY_FULL"}
        old_location = str(instance.get("location", ""))
        old_owned = self._item_owned_state(
            instance.get("location"), instance.get("owner_id")
        )
        old_definition_id = str(instance.get("definition_id", ""))
        quantity = max(1, int(instance.get("quantity", 1)))
        ok, result = item_state.transition_instance(
            instance,
            location,
            owner_id=owner_id,
            container_id=container_id,
            equipped_slot=equipped_slot,
            position=position,
        )
        if not ok:
            return ok, result
        self._instance_item_transition_locked(instance,old_location)
        if str(location).upper() != "INVENTORY" or old_location != "INVENTORY":
            instance["slot_index"] = -1
        new_owned = self._item_owned_state(
            instance.get("location"), instance.get("owner_id")
        )
        if new_owned:self._bind_acquired_item_locked(instance)
        if old_owned != new_owned:
            change = quantity if new_owned else -quantity
            self._inventory[old_definition_id] = max(
                0, int(self._inventory.get(old_definition_id, 0)) + change
            )
            if self._inventory[old_definition_id] <= 0:
                self._inventory.pop(old_definition_id, None)
        return ok, result

    def _sync_saved_player_items_locked(self) -> None:
        """Keep an earlier in-memory character save consistent with bank transfers."""
        # Service transactions publish inventory, social state and coins in
        # one save. A nested barter must not checkpoint half that transaction.
        if getattr(self,'_service_atomic_active',False):return
        saved = self._state_store.load(self._persistence_key)
        if not isinstance(saved, dict):
            return
        saved["item_instances"] = copy.deepcopy(list(self._item_instances.values()))
        saved["inventory"] = dict(self._inventory)
        result = self._state_store.save(self._persistence_key, saved)
        self._persistence_revision = int(result["revision"])

    def _reconcile_item_instances_locked(self) -> None:
        """Keep legacy count inventory and instance state losslessly aligned."""
        # A consumed instance has no live ownership or buyback claim. Reclaim
        # old tombstones before allocating so repeated crafting cannot exhaust
        # the bounded world registry. Instance IDs remain monotonic.
        for key, row in list(self._item_instances.items()):
            if isinstance(row, dict) and row.get("location") == "DESTROYED":
                self._item_instances.pop(key)
        actual: dict[str, int] = {}
        for row in self._item_instances.values():
            if not isinstance(row, dict) or not self._item_owned_state(
                row.get("location"), row.get("owner_id")
            ):
                continue
            definition_id = str(row.get("definition_id", ""))
            actual[definition_id] = actual.get(definition_id, 0) + max(
                1, int(row.get("quantity", 1))
            )

        # Deduct every ingredient first: its freed bag/world slots belong to
        # this same transaction, regardless of inventory dictionary order.
        for definition_id, expected_raw in list(self._inventory.items()):
            expected = max(0, int(expected_raw))
            current = actual.get(definition_id, 0)
            if expected >= current:
                continue
            remaining = current - expected
            for row in reversed(list(self._item_instances.values())):
                if remaining <= 0:
                    break
                if not isinstance(row, dict) or str(row.get("definition_id")) != definition_id:
                    continue
                if str(row.get("location")) != "INVENTORY" or str(row.get("owner_id")) != "player":
                    continue
                quantity = max(1, int(row.get("quantity", 1)))
                removed = min(quantity, remaining)
                if removed >= quantity:
                    item_state.transition_instance(row, "DESTROYED", owner_id="")
                    self._item_instances.pop(str(row["instance_id"]), None)
                else:
                    row["quantity"] = quantity - removed
                remaining -= removed

        for definition_id, expected_raw in list(self._inventory.items()):
            remaining = max(0, int(expected_raw)) - actual.get(definition_id, 0)
            if remaining <= 0:
                continue
            definition = item_state.definition(self._item_catalog, definition_id) or {}
            stack_limit = max(1, int(definition.get("stack_limit", 1)))
            while remaining > 0 and len(self._item_instances) < item_state.MAX_WORLD_INSTANCES:
                instance_id = self._next_item_instance_id_locked("inventory-stack")
                quantity = min(stack_limit, remaining)
                self._item_instances[instance_id] = item_state.make_instance(
                    self._item_catalog,
                    instance_id,
                    definition_id,
                    location="INVENTORY",
                    quantity=quantity,
                    owner_id="player",
                )
                remaining -= quantity

        for row in self._item_instances.values():
            if isinstance(row,dict):self._bind_acquired_item_locked(row)
        # Crafting can spend the last ingredient while retaining a zero count.
        # Physical inventory has no zero-quantity stacks; preserve the same
        # canonical count map before the next saved service validates custody.
        for definition_id, quantity in tuple(self._inventory.items()):
            if quantity == 0:
                self._inventory.pop(definition_id)

    def _select_player_gear_locked(
        self,
        instance_id: str = "",
    ) -> dict[str, Any] | None:
        wanted = str(instance_id or "")
        if wanted:
            row = self._item_instance_locked(wanted)
            if (
                isinstance(row, dict)
                and str(row.get("owner_id")) == "player"
                and str(row.get("location")) in item_state.PLAYER_OWNED_LOCATIONS
                and isinstance(row.get("gear"), dict)
            ):
                return row
            return None
        candidates = [
            row
            for row in self._item_instances.values()
            if isinstance(row, dict)
            and str(row.get("owner_id")) == "player"
            and str(row.get("location")) in item_state.PLAYER_OWNED_LOCATIONS
            and isinstance(row.get("gear"), dict)
        ]
        candidates.sort(
            key=lambda row: (
                0 if str(row.get("location")) == "EQUIPPED" else 1,
                str(row.get("instance_id", "")),
            )
        )
        return candidates[0] if candidates else None

    def _consume_inventory_item_locked(
        self,
        instance: dict[str, Any],
        quantity: int = 1,
    ) -> bool:
        if self._item_binding_locked(instance):return False
        if (
            not isinstance(instance, dict)
            or str(instance.get("location")) != "INVENTORY"
            or str(instance.get("owner_id")) != "player"
        ):
            return False
        amount = max(1, int(quantity))
        definition_id = str(instance.get("definition_id", ""))
        current = max(1, int(instance.get("quantity", 1)))
        available = max(0, int(self._inventory.get(definition_id, 0)))
        if available < amount or current < amount:
            return False
        if current > amount:
            instance["quantity"] = current - amount
        else:
            self._item_instances.pop(str(instance.get("instance_id", "")), None)
        remaining = available - amount
        if remaining > 0:
            self._inventory[definition_id] = remaining
        else:
            self._inventory.pop(definition_id, None)
        return True

    def _nearest_item_locked(
        self,
        instance_id: str = "",
        *,
        container_only: bool = False,
    ) -> tuple[dict[str, Any] | None, float]:
        wanted = str(instance_id or "")
        best: dict[str, Any] | None = None
        best_distance = float("inf")
        for key in sorted(self._item_instances):
            row = self._item_instances[key]
            if not isinstance(row, dict) or str(row.get("location")) != "GROUND" or not self._instance_item_visible_locked(row):
                continue
            is_container = str(row.get("kind")) == "CONTAINER"
            if container_only and not is_container:
                continue
            if wanted and key != wanted:
                continue
            position = row.get("position", {})
            try:
                distance = math.hypot(
                    float(position.get("x", 0.0)) - self._x[0],
                    float(position.get("z", 0.0)) - self._z[0],
                )
            except (TypeError, ValueError):
                continue
            if distance > item_state.INTERACTION_RADIUS_M:
                continue
            if distance > best_distance or (
                abs(distance - best_distance) <= 0.0001
                and best is not None
                and key >= str(best.get("instance_id"))
            ):
                continue
            best = row
            best_distance = distance
        return best, best_distance

    def _ambient_life_rows_locked(self, *, include_identity: bool = True) -> list[dict[str, Any]]:
        if self._instance_private_locked():return []
        """Return schedule/stimulus-aware render-only population proxies."""
        if self._world_population.active and math.hypot(self._x[0],self._z[0])>384:
            # Release the starter crowd's rig slots while visiting another
            # region. Their saved routes/identities keep running logically.
            return []
        rows = life_contract.proxy_rows(
            self._life_spawns,
            self._sim_time,
            player_x=self._x[0],
            player_z=self._z[0],
            terrain_height=self._terrain_height_locked,
            render_radius_m=life_contract.RENDER_RADIUS_M,
        )
        for row in rows:
            x = float(row.get("x", 0.0))
            z = float(row.get("z", 0.0))
            row["cell_key"] = world.cell_key(
                world.chunk_coord(x),
                world.chunk_coord(z),
            )
            row["lod"] = world.lod_tier_for_screen_error(
                64.0 / max(1.0, math.hypot(x - self._x[0], z - self._z[0]) ** 2)
            )
            if include_identity:
                row["individual"] = identity_contract.view(
                    self._individual_state,
                    row.get("id", ""),
                )
        return rows

    def _world_people_rows_locked(self):
        if self._instance_private_locked():return []
        rows=self._world_population.rows(self._sim_time,self._x[0],self._z[0],self._terrain_height_locked)
        cache=getattr(self,'_world_actor_assets',None)
        if cache is None:cache=self._world_actor_assets={}
        for rank,row in enumerate(rows,start=len(self._npc_indices)+1):
            pose=row.get('animation') or {}
            action_clip = self._decorate_character_animation_locked(pose, row['id'])
            state=pose.get('locomotion',pose.get('state','IDLE'));key=(row['id'],state,rank,action_clip)
            if key not in cache:
                cache[key]=assets_contract.entity_binding(self._asset_catalog,state,pose.get('phase',0),rank,asset_role='CROWD',clip_override=action_clip,
                    variant_index=row['individual']['appearance_index']+len(self._asset_catalog.get('crowd_variants',[]))*
                    (int.from_bytes(__import__('hashlib').blake2s((row['id']+':shape').encode(),digest_size=4).digest(),'little')%36))
                if len(cache)>48:del cache[next(iter(cache))]
            row['asset']=cache[key]
            row['cell_key']=world.cell_key(world.chunk_coord(row['x']),world.chunk_coord(row['z']))
            row['lod']='NEAR'
        return rows

    def _promote_life_actor_locked(
        self,
        spawn: dict[str, Any],
        *,
        record_event: bool = True,
    ) -> bool:
        """Turn one ambient proxy into a real pooled NPC at its live position."""
        if not isinstance(spawn, dict):
            return False
        identity_id = str(spawn.get("id", "")).strip()
        if not identity_id or identity_id in self._promoted_life_ids:
            return False
        proxy_rows = life_contract.proxy_rows(
            [spawn],
            self._sim_time,
            player_x=self._x[0],
            player_z=self._z[0],
            terrain_height=self._terrain_height_locked,
        )
        proxy = proxy_rows[0] if proxy_rows else spawn
        role = str(spawn.get("role", "TRAVELER")).upper()
        archetype = "CRITTER" if role in {"CRITTER", "WILDLIFE"} else "WANDERER"
        proxy_scale = (
            _clamp(proxy.get("sx"), 0.35, 3.0, 0.8),
            _clamp(proxy.get("sy"), 0.35, 3.0, 1.0),
            _clamp(proxy.get("sz"), 0.35, 3.0, 0.8),
        )
        actor_spawn = {
            "id": identity_id,
            "archetype": archetype,
            "x": _clamp(proxy.get("x"), -1000000.0, 1000000.0),
            "z": _clamp(proxy.get("z"), -1000000.0, 1000000.0),
            "scale": proxy_scale,
            "color": str(proxy.get("color", spawn.get("color", "#8db89a"))),
            "phase": _clamp(spawn.get("phase"), -1000.0, 1000.0),
        }
        slot = self._spawn_npc_locked(actor_spawn)
        if slot is None:
            return False
        # Promotion changes the simulation tier, not the authored spawn point.
        # The live position above is used for this handoff; the fixed home is
        # retained for a later death/respawn and bounded walking return.
        self._npc_home_x[slot] = float(spawn.get('x',self._x[slot]))
        self._npc_home_z[slot] = float(spawn.get('z',self._z[slot]))
        self._yaw[slot] = float(proxy.get('yaw',0))
        self._vx[slot] = float(proxy.get('speed',0))*math.sin(self._yaw[slot])
        self._vz[slot] = float(proxy.get('speed',0))*math.cos(self._yaw[slot])
        self._promoted_life_ids.add(identity_id)
        self._life_spawns = [
            row
            for row in self._life_spawns
            if str(row.get("id", "")) != identity_id
        ]
        if record_event:
            self._append_event_locked(
                "NPC_PROMOTED",
                f"{identity_id} entered the full simulation as a nearby resident.",
                actor_id=identity_id,
                subject_id="POPULATION_PROMOTION",
                target_id=identity_id,
                payload={
                    "role": role,
                    "archetype": archetype,
                    "source": "AMBIENT_LOD_PROMOTION",
                    "position": {
                        "x": round(self._x[slot], 3),
                        "z": round(self._z[slot], 3),
                    },
                },
            )
        return True

    def _tick_world_events_locked(self) -> None:
        if self._instance_private_locked():return
        """Apply scheduled event facts to the shared item/faction/NPC state."""
        result = world_events_contract.tick(
            self._world_event_state,
            self._world_event_catalog,
            self._sim_time,
        )
        for change in result.get("changes", [])[: world_events_contract.MAX_ACTIVE * 2]:
            if not isinstance(change, dict):
                continue
            event = change.get("event") if isinstance(change.get("event"), dict) else {}
            event_id = str(event.get("id", ""))
            phase = str(change.get("phase", "")).upper()
            if phase == "START":
                location = event.get("location", {}) if isinstance(event.get("location"), dict) else {}
                definition_id = str(event.get("reward_item_id", ""))
                if item_state.definition(self._item_catalog, definition_id) is None:
                    rolled = item_state.roll_loot(
                        self._item_catalog,
                        self._tick * 4099 + sum(ord(char) for char in event_id),
                        str(event.get("loot_table_id", "")),
                    )
                    definition_id = str(rolled.get("item_id", ""))
                    quantity = max(1, _safe_int(rolled.get("quantity"), 1))
                else:
                    quantity = max(1, _safe_int(event.get("reward_quantity"), 1))
                created_id = ""
                if (
                    definition_id
                    and item_state.definition(self._item_catalog, definition_id) is not None
                    and len(self._item_instances) < item_state.MAX_WORLD_INSTANCES
                ):
                    x = _clamp(location.get("x"), -1000000.0, 1000000.0)
                    z = _clamp(location.get("z"), -1000000.0, 1000000.0)
                    created_id = f"event-drop-{event_id}"[:64]
                    if created_id not in self._item_instances:
                        instance = item_state.make_instance(
                            self._item_catalog,
                            created_id,
                            definition_id,
                            location="GROUND",
                            quantity=quantity,
                            position={
                                "x": x,
                                "y": self._terrain_height_locked(x, z),
                                "z": z,
                            },
                            visual_phase=(sum(ord(char) for char in created_id) % 100) / 17.0,
                        )
                        instance["origin"] = "WORLD_EVENT"
                        instance["origin_id"] = event_id
                        instance["roll_table_id"] = str(event.get("loot_table_id", ""))[:96]
                        self._item_instances[created_id] = instance
                    else:
                        created_id = ""
                faction_results = []
                for faction_id, amount in list(event.get("standing", {}).items())[:8]:
                    faction_results.append(
                        factions_contract.adjust_player(
                            self._faction_state,
                            faction_id,
                            amount,
                            source=f"WORLD_EVENT:{event_id}",
                            sim_time=self._sim_time,
                        )
                    )
                people = self._individual_state.get("individuals", {})
                if isinstance(people, dict):
                    for identity_id in sorted(people)[: identity_contract.MAX_INDIVIDUALS]:
                        person = people.get(identity_id)
                        if not isinstance(person, dict):
                            continue
                        identity_contract.record_memory(
                            self._individual_state,
                            identity_id,
                            "WORLD_EVENT",
                            event_id,
                            self._sim_time,
                            text=f"Heard the event: {event.get('name', event_id)}",
                            weight=0.72,
                        )
                self._append_event_locked(
                    "WORLD_EVENT_START",
                    f"{event.get('name', event_id)} began at the living frontier.",
                    actor_id="world",
                    subject_id=event_id,
                    target_id=created_id,
                    payload={
                        "event_id": event_id,
                        "faction_results": faction_results,
                        "reward_definition_id": definition_id,
                        "reward_instance_id": created_id,
                    },
                )
            elif phase == "COMPLETE":
                self._append_event_locked(
                    "WORLD_EVENT_COMPLETE",
                    f"{event.get('name', event_id)} passed into the island's history.",
                    actor_id="world",
                    subject_id=event_id,
                    payload={"event_id": event_id},
                )

    def _tick_population_locked(self) -> None:
        if self._instance_private_locked():return
        """Promote one nearby person at a time without growing the render list."""
        if self._stress or len(self._promoted_life_ids) >= MAX_POPULATION_PROMOTIONS:
            return
        if self._sim_time < POPULATION_PROMOTION_INTERVAL_S:
            return
        if self._sim_time - self._last_population_promotion_s < POPULATION_PROMOTION_INTERVAL_S:
            return
        self._last_population_promotion_s = self._sim_time
        if not self._life_spawns:
            return
        physical_positions = [
            (self._x[index], self._z[index])
            for index in self._npc_indices
            if self._alive[index]
        ]
        candidates: list[tuple[float, str, dict[str, Any]]] = []
        for spawn in self._life_spawns:
            if not isinstance(spawn, dict):
                continue
            # Main road circuits retain their authored route. Local residents
            # may enter the bounded full AI at their current live position.
            if spawn.get("waypoints") and not spawn.get("allow_promotion"):
                continue
            rows = life_contract.proxy_rows(
                [spawn],
                self._sim_time,
                player_x=self._x[0],
                player_z=self._z[0],
                terrain_height=self._terrain_height_locked,
            )
            row = rows[0] if rows else spawn
            x = _clamp(row.get("x"), -1000000.0, 1000000.0)
            z = _clamp(row.get("z"), -1000000.0, 1000000.0)
            if math.hypot(x-self._x[0],z-self._z[0])>life_contract.RENDER_RADIUS_M:
                continue
            nearest = min(
                [math.hypot(x - px, z - pz) for px, pz in physical_positions]
                or [math.hypot(x - self._x[0], z - self._z[0])]
            )
            candidates.append((nearest, str(spawn.get("id", "")), spawn))
        candidates.sort(key=lambda row: (row[0], row[1]))
        if candidates:
            self._promote_life_actor_locked(candidates[0][2])

    def _social_active_positions_locked(
        self,
        active_ids: list[str],
    ) -> dict[str, tuple[float, float]]:
        positions = self._individual_world_positions_locked(active_ids)
        for index in self._npc_indices:
            if not self._alive[index]:
                continue
            actor = self._combat_state.get("actors", {}).get(self._npc_ids[index])
            if isinstance(actor, dict) and not actor.get("alive", True):
                positions.pop(str(self._npc_ids[index]), None)
        return positions

    def _handle_npc_vs_npc_defeat_locked(
        self,
        attacker_id: str,
        defender_id: str,
        defender_index: int,
        attack_result: dict[str, Any],
    ) -> dict[str, Any]:
        """Commit an off-player defeat using the same real loot/XP seams."""
        loot_result = self._spawn_combat_loot_locked(defender_id, defender_index)
        people = self._individual_state.get("individuals", {})
        attacker = people.get(attacker_id) if isinstance(people, dict) else None
        xp_result: dict[str, Any] = {}
        power_result: dict[str, Any] = {}
        if isinstance(attacker, dict):
            progression_state = attacker.get("progression")
            if not isinstance(progression_state, dict):
                progression_state = npc_progression.starter_state(
                    attacker_id,
                    role=attacker.get("role"),
                    archetype=attacker.get("archetype"),
                    occupation=attacker.get("occupation"),
                )
                attacker["progression"] = progression_state
            xp_result = npc_progression.grant_xp(
                progression_state,
                24 + max(1, int(self._npc_combat_profile_locked(defender_id).get("level", 1))) * 6,
                source="NPC_COMBAT",
                sim_time=self._sim_time,
            )
            power_result = self._refresh_npc_progression_locked(
                attacker_id,
                attacker,
                source="NPC_COMBAT",
            )
            identity_contract.record_memory(
                self._individual_state,
                attacker_id,
                "NPC_DEFEAT",
                defender_id,
                self._sim_time,
                text=f"Won a real encounter with {defender_id}.",
                weight=0.84,
            )
        defender = people.get(defender_id) if isinstance(people, dict) else None
        if isinstance(defender, dict):
            identity_contract.record_memory(
                self._individual_state,
                defender_id,
                "NPC_DEFEAT",
                attacker_id,
                self._sim_time,
                text=f"Was defeated by {attacker_id}; the next meeting will matter.",
                weight=1.0,
            )
        self._vx[defender_index] = 0.0
        self._vz[defender_index] = 0.0
        self._npc_state[defender_index] = "DEAD"
        self._npc_reason[defender_index] = "NPC_COMBAT_DEFEATED"
        result = {
            "loot": loot_result,
            "xp": xp_result,
            "power": power_result,
            "attacker_id": attacker_id,
            "defender_id": defender_id,
        }
        if xp_result.get("xp_gained"):
            self._append_event_locked(
                "NPC_PROGRESSION",
                f"{attacker_id} gained real combat experience from {defender_id}.",
                actor_id=attacker_id,
                subject_id="XP",
                target_id=defender_id,
                payload=copy.deepcopy(xp_result),
            )
        if power_result.get("changed"):
            self._append_event_locked(
                "NPC_POWER_CHANGED",
                f"{attacker_id}'s real power changed after the encounter.",
                actor_id=attacker_id,
                subject_id="POWER",
                target_id=attacker_id,
                payload=copy.deepcopy(power_result),
            )
        self._append_event_locked(
            "NPC_COMBAT_DEFEAT",
            f"{attacker_id} defeated {defender_id}; the world retained a real loot drop.",
            actor_id=attacker_id,
            subject_id="DEFEAT",
            target_id=defender_id,
            payload={"attack": copy.deepcopy(attack_result), **copy.deepcopy(result)},
        )
        return result

    def _resolve_npc_conflict_locked(
        self,
        encounter: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        first_id = str(encounter.get("a_id", ""))
        second_id = str(encounter.get("b_id", ""))
        first_index = self._npc_index_for_id_locked(first_id)
        second_index = self._npc_index_for_id_locked(second_id)
        if first_index is None or second_index is None:
            return "CONFLICT_NO_PHYSICAL_ACTORS", {}
        self._ensure_combat_actors_locked()
        first_person = self._individual_state.get("individuals", {}).get(first_id)
        second_person = self._individual_state.get("individuals", {}).get(second_id)
        first_profile = self._npc_combat_profile_locked(first_id, first_person)
        second_profile = self._npc_combat_profile_locked(second_id, second_person)
        result = combat_contract.resolve_attack(
            self._combat_state,
            attacker_id=first_id,
            defender_id=second_id,
            attacker_profile=first_profile,
            defender_profile=second_profile,
            sim_time=self._sim_time,
            seed=self._tick * 19 + first_index * 31 + second_index * 7,
            action_id="npc_conflict",
        )
        if not result.get("ok"):
            return str(result.get("status", "CONFLICT_BLOCKED")), result
        self._start_character_action_locked(first_id, "UnarmedAttack")
        self._start_character_action_locked(
            second_id, "Death" if result.get("defeated") else "HitReact"
        )
        self._last_combat = copy.deepcopy(result)
        self._append_event_locked(
            "NPC_COMBAT_ATTACK",
            f"{first_id} hit {second_id} for {result.get('damage', 0)}.",
            actor_id=first_id,
            subject_id="NPC_CONFLICT",
            target_id=second_id,
            payload=copy.deepcopy(result),
        )
        if result.get("defeated"):
            result["defeat"] = self._handle_npc_vs_npc_defeat_locked(
                first_id,
                second_id,
                second_index,
                result,
            )
        return str(result.get("status", "HIT")), result

    def _tick_social_locked(self) -> None:
        """Commit a bounded nearby NPC meeting at the individual cadence."""
        if self._tick % 30 != 0:
            return
        active_ids = [
            str(self._npc_ids[index])
            for index in self._npc_indices
            if self._alive[index] and self._npc_ids[index]
        ]
        active_ids.extend(
            str(row.get("id", ""))
            for row in self._life_spawns
            if isinstance(row, dict) and row.get("id")
        )
        people = self._individual_state.get("individuals", {})
        if not isinstance(people, dict):
            return
        positions = self._social_active_positions_locked(active_ids)
        pairs = social_contract.nearby_pairs(
            people,
            positions,
            self._social_state,
            self._sim_time,
        )
        physical_ids = {
            str(self._npc_ids[index])
            for index in self._npc_indices
            if self._alive[index] and self._npc_ids[index]
        }
        for encounter in pairs[: social_contract.MAX_PAIRS_PER_PASS]:
            kind = str(encounter.get("kind", "CONVERSE")).upper()
            first_id = str(encounter.get("a_id", ""))
            second_id = str(encounter.get("b_id", ""))
            if kind == "CONFLICT":
                if first_id not in physical_ids or second_id not in physical_ids:
                    continue
                outcome, combat_result = self._resolve_npc_conflict_locked(encounter)
            else:
                outcome = "CONVERSATION"
                combat_result = {}
                identity_contract.record_memory(
                    self._individual_state,
                    first_id,
                    "NPC_MEETING",
                    second_id,
                    self._sim_time,
                    text=f"Met {second_id} while moving through the island.",
                    weight=0.58,
                )
                identity_contract.record_memory(
                    self._individual_state,
                    second_id,
                    "NPC_MEETING",
                    first_id,
                    self._sim_time,
                    text=f"Met {first_id} while moving through the island.",
                    weight=0.58,
                )
            social_result = social_contract.record(
                self._social_state,
                encounter,
                self._sim_time,
                outcome=outcome,
            )
            self._append_event_locked(
                "NPC_SOCIAL",
                f"{first_id} and {second_id}: {outcome.lower()}.",
                actor_id=first_id,
                subject_id=kind,
                target_id=second_id,
                payload={
                    "encounter": copy.deepcopy(encounter),
                    "outcome": outcome,
                    "social": copy.deepcopy(social_result),
                    "combat": copy.deepcopy(combat_result),
                },
            )

    def _world_use_rows_locked(self) -> list[dict[str, Any]]:
        """Expose nearby loot and stations to the low-rate individual layer."""
        rows: list[dict[str, Any]] = []
        for instance_id in sorted(self._item_instances):
            item = self._item_instances[instance_id]
            if not isinstance(item, dict) or str(item.get("location")) not in {
                "GROUND",
                "CONTAINER",
            }:
                continue
            position = item.get("position", {})
            if str(item.get("location")) == "CONTAINER":
                container = self._item_instances.get(str(item.get("container_id", "")))
                if isinstance(container, dict):
                    position = container.get("position", position)
            definition = item_state.definition(
                self._item_catalog,
                item.get("definition_id"),
            ) or {}
            rows.append(
                {
                    "id": str(instance_id),
                    "kind": "CONTAINER"
                    if str(item.get("kind")) == "CONTAINER"
                    else str(item.get("kind", "ITEM")),
                    "definition_id": str(item.get("definition_id", "")),
                    "rarity": str(item.get("rarity", "COMMON")),
                    "level": max(1, int(item.get("level", 1))),
                    "gear_score": npc_progression.item_score(item),
                    "tags": list(definition.get("tags", []))[:8]
                    if isinstance(definition, dict)
                    else [],
                    "x": _clamp(position.get("x"), -1000000.0, 1000000.0),
                    "z": _clamp(position.get("z"), -1000000.0, 1000000.0),
                }
            )
            if len(rows) >= 32:
                break
        if len(rows) < 32:
            rows.extend(
                {
                    "id": station["id"],
                    "kind": "STATION",
                    "tags": station.get("tags", []),
                    "x": station.get("x", 0.0),
                    "z": station.get("z", 0.0),
                }
                for station in gear_contract.world_stations(self._gear_tables)[
                    : max(0, 32 - len(rows))
                ]
            )
        return rows[:32]

    def _tick_individuals_locked(self) -> None:
        if self._instance_private_locked():return
        """Run the social/world-use layer at 2 Hz, below the physics cadence."""
        if self._tick % 30 != 0:
            return
        active_ids = [self._npc_ids[index] for index in self._npc_indices]
        active_ids.extend(str(row.get("id", "")) for row in self._life_spawns)
        before: dict[str, tuple[str, str]] = {}
        for identity_id in active_ids:
            person = self._individual_state.get("individuals", {}).get(identity_id)
            if not isinstance(person, dict):
                continue
            target = person.get("target")
            target_id = str(target.get("id", "")) if isinstance(target, dict) else ""
            before[str(identity_id)] = (
                str(person.get("activity", "WANDER")),
                target_id,
            )
        identity_contract.tick(
            self._individual_state,
            self._sim_time,
            player_x=self._x[0],
            player_z=self._z[0],
            world_items=self._world_use_rows_locked(),
            stations=gear_contract.world_stations(self._gear_tables),
            active_ids=active_ids,
        )
        people = self._individual_state.get("individuals", {})
        for identity_id in active_ids:
            person = people.get(identity_id) if isinstance(people, dict) else None
            if not isinstance(person, dict):
                continue
            target = person.get("target")
            target_id = str(target.get("id", "")) if isinstance(target, dict) else ""
            activity = str(person.get("activity", "WANDER"))
            if before.get(str(identity_id)) == (activity, target_id):
                continue
            self._append_event_locked(
                "NPC_WORLD_INTENT",
                f"{identity_id} chose {activity.lower()}" + (
                    f" toward {target_id}." if target_id else "."
                ),
                actor_id=str(identity_id),
                subject_id=activity,
                target_id=target_id,
                payload={
                    "activity": activity,
                    "target": target if isinstance(target, dict) else {},
                    "revision": person.get("revision", 0),
                },
            )
        positions = self._individual_world_positions_locked(active_ids)
        committed = 0
        for identity_id in sorted(set(str(value) for value in active_ids)):
            if committed >= MAX_NPC_WORLD_ACTIONS_PER_PASS:
                break
            person = people.get(identity_id) if isinstance(people, dict) else None
            position = positions.get(identity_id)
            if not isinstance(person, dict) or position is None:
                continue
            if self._execute_npc_world_action_locked(identity_id, person, position):
                committed += 1
        self._tick_vendor_economy_locked()

    def _vendor_stock_breakdown_locked(
        self,
        vendor: dict[str, Any],
    ) -> dict[str, int]:
        """Count actual tradeable vendor POCKET instances by definition."""
        if not isinstance(vendor, dict):
            return {}
        npc_id = str(vendor.get("npc_id", ""))
        breakdown: dict[str, int] = {}
        for instance in self._item_instances.values():
            if not isinstance(instance, dict):
                continue
            candidate_id = str(instance.get("definition_id", ""))
            if (
                str(instance.get("owner_id", "")) != npc_id
                or str(instance.get("location", "")) != "POCKET"
            ):
                continue
            price = economy_contract.pricing_row(vendor, candidate_id)
            definition = item_state.definition(self._item_catalog, candidate_id)
            if price is None or not economy_contract.is_tradeable_definition(definition):
                continue
            breakdown[candidate_id] = breakdown.get(candidate_id, 0) + 1
        return breakdown

    def _vendor_stock_count_locked(
        self,
        vendor: dict[str, Any],
        definition_id: str = "",
    ) -> int:
        """Count actual tradeable vendor POCKET instances, never references."""
        breakdown = self._vendor_stock_breakdown_locked(vendor)
        if definition_id:
            return breakdown.get(str(definition_id), 0)
        return sum(breakdown.values())

    def _tick_vendor_economy_locked(self) -> None:
        if self._instance_private_locked():return
        """Let live vendor NPCs replenish physical stock on a fixed cadence."""
        people = self._individual_state.get("individuals", {})
        accounts = self._economy_state.get("vendors", {})
        if not isinstance(people, dict) or not isinstance(accounts, dict):
            return
        for vendor_id in sorted(self._vendor_catalog)[: economy_contract.MAX_VENDORS]:
            vendor = self._vendor_catalog.get(vendor_id)
            account = accounts.get(vendor_id)
            if not isinstance(vendor, dict) or not isinstance(account, dict):
                continue
            identity_id = str(vendor.get("npc_id", ""))
            person = people.get(identity_id)
            if not isinstance(person, dict):
                continue
            if not any(
                self._alive[index] and str(self._npc_ids[index]) == identity_id
                for index in self._npc_indices
            ):
                continue
            stock_by_definition = self._vendor_stock_breakdown_locked(vendor)
            stock_count = sum(stock_by_definition.values())
            plan = economy_contract.restock_plan(
                vendor,
                account,
                stock_count,
                self._sim_time,
            )
            if not plan.get("due"):
                continue

            decision = economy_contract.vendor_restock_decision(
                vendor,
                account,
                person.get("needs", {}),
                plan,
                stock_by_definition,
            )
            if decision.get("action") == "HOLD":
                recorded_decision = economy_contract.record_vendor_decision(
                    account,
                    self._sim_time,
                    decision,
                )
                self._append_event_locked(
                    "VENDOR_DECISION",
                    f"{vendor_id} held restock: {recorded_decision.get('reason', 'HOLD')}.",
                    actor_id=identity_id,
                    subject_id="RESTOCK",
                    target_id=str(vendor_id),
                    payload={
                        "vendor_id": str(vendor_id),
                        "npc_id": identity_id,
                        "decision": recorded_decision,
                        "stock_count": stock_count,
                    },
                )
                continue

            inventory_refs = person.get("inventory")
            if not isinstance(inventory_refs, list):
                inventory_refs = []
            max_items = max(0, int(plan.get("max_items", 0)))
            if (
                len(self._item_instances) + max_items > item_state.MAX_WORLD_INSTANCES
                or len(inventory_refs) + max_items > identity_contract.MAX_CARRIED_ITEMS
                or sum(
                    1
                    for row in self._item_instances.values()
                    if isinstance(row, dict)
                    and str(row.get("location", "")) == "POCKET"
                )
                + max_items
                > item_state.MAX_POCKET_ITEMS
            ):
                restock = economy_contract.record_restock_attempt(
                    account,
                    self._sim_time,
                    success=False,
                    status="CAPACITY_BLOCKED",
                    table_id=plan.get("table_id"),
                    seed=plan.get("seed"),
                )
                recorded_decision = economy_contract.record_vendor_decision(
                    account,
                    self._sim_time,
                    decision,
                )
                self._append_event_locked(
                    "VENDOR_RESTOCK_BLOCKED",
                    f"{vendor_id} could not restock within the item budget.",
                    actor_id=identity_id,
                    subject_id="RESTOCK",
                    target_id=str(vendor_id),
                    payload={
                        "vendor_id": str(vendor_id),
                        "npc_id": identity_id,
                        "status": restock.get("status", "CAPACITY_BLOCKED"),
                        "table_id": plan.get("table_id", ""),
                        "seed": plan.get("seed", 0),
                        "decision": recorded_decision,
                    },
                )
                continue

            candidates: list[dict[str, Any]] = []
            rolled_definition_ids: list[str] = []
            prospective_stock = dict(stock_by_definition)
            for slot in range(max_items):
                rolled_candidates: list[dict[str, Any]] = []
                for attempt in range(4):
                    roll_seed = int(plan.get("seed", 1)) + slot * 4 + attempt
                    rolled = item_state.roll_loot(
                        self._item_catalog,
                        roll_seed,
                        str(plan.get("table_id", "")),
                    )
                    definition_id = str(rolled.get("item_id", ""))
                    definition = item_state.definition(
                        self._item_catalog,
                        definition_id,
                    )
                    quote = economy_contract.dynamic_prices(
                        vendor,
                        account,
                        definition_id,
                        stock_count + len(candidates),
                    )
                    if (
                        economy_contract.is_tradeable_definition(definition)
                        and quote is not None
                        and quote.get("buy", 0) > 0
                    ):
                        rolled_candidates.append(
                            {
                                "seed": roll_seed,
                                "roll": rolled,
                                "definition_id": definition_id,
                                "quantity": max(1, int(rolled.get("quantity", 1))),
                                "ordinal": attempt,
                            }
                        )
                        rolled_definition_ids.append(definition_id)
                selected = economy_contract.choose_restock_candidate(
                    vendor,
                    rolled_candidates,
                    prospective_stock,
                    current_stock=stock_count + len(candidates),
                )
                if selected is not None:
                    candidates.append(selected)
                    selected_definition_id = str(selected.get("definition_id", ""))
                    prospective_stock[selected_definition_id] = (
                        prospective_stock.get(selected_definition_id, 0) + 1
                    )

            if not candidates:
                restock = economy_contract.record_restock_attempt(
                    account,
                    self._sim_time,
                    success=False,
                    status="NO_TRADEABLE_LOOT",
                    table_id=plan.get("table_id"),
                    seed=plan.get("seed"),
                )
                decision["rolled_definition_ids"] = rolled_definition_ids
                recorded_decision = economy_contract.record_vendor_decision(
                    account,
                    self._sim_time,
                    decision,
                )
                self._append_event_locked(
                    "VENDOR_RESTOCK_BLOCKED",
                    f"{vendor_id} found no tradeable loot in its restock table.",
                    actor_id=identity_id,
                    subject_id="RESTOCK",
                    target_id=str(vendor_id),
                    payload={
                        "vendor_id": str(vendor_id),
                        "npc_id": identity_id,
                        "status": restock.get("status", "NO_TRADEABLE_LOOT"),
                        "table_id": plan.get("table_id", ""),
                        "seed": plan.get("seed", 0),
                        "decision": recorded_decision,
                    },
                )
                continue

            decision["rolled_definition_ids"] = rolled_definition_ids
            decision["selected_definition_id"] = str(
                candidates[0].get("definition_id", "")
            )
            decision["focus_definition_id"] = decision["selected_definition_id"]
            decision["selected_seed"] = int(candidates[0].get("seed", 0))
            item_counter_backup = self._item_counter
            person_backup = copy.deepcopy(person)
            account_backup = copy.deepcopy(account)
            created: list[dict[str, Any]] = []
            created_ids: list[str] = []
            try:
                recorded_decision = economy_contract.record_vendor_decision(
                    account,
                    self._sim_time,
                    decision,
                )
                for candidate in candidates:
                    instance_id = self._next_item_instance_id_locked(
                        f"vendor-{vendor_id}-stock"
                    )
                    while instance_id in self._item_instances:
                        instance_id = self._next_item_instance_id_locked(
                            f"vendor-{vendor_id}-stock"
                        )
                    instance = item_state.make_instance(
                        self._item_catalog,
                        instance_id,
                        candidate["definition_id"],
                        location="POCKET",
                        quantity=candidate["quantity"],
                        owner_id=identity_id,
                        visual_phase=(self._item_counter % 17) * 0.31,
                    )
                    loot_record = candidate["roll"]
                    affix_payload = content_catalog.deterministic_loot(
                        self._content,
                        candidate["seed"],
                        base_item_id=candidate["definition_id"],
                    )
                    instance["seed"] = candidate["seed"]
                    instance["base_item_id"] = candidate["definition_id"]
                    instance["roll_table_id"] = str(plan.get("table_id", ""))[:96]
                    instance["roll"] = max(0, int(loot_record.get("roll", 0)))
                    instance["origin"] = "VENDOR_RESTOCK"
                    instance["affixes"] = copy.deepcopy(
                        affix_payload.get("affixes", [])[:2]
                    )
                    self._item_instances[instance_id] = instance
                    created_ids.append(instance_id)
                    inventory_refs.append(candidate["definition_id"])
                    created.append(instance)
                person["inventory"] = inventory_refs[: identity_contract.MAX_CARRIED_ITEMS]
                restock = economy_contract.record_restock_attempt(
                    account,
                    self._sim_time,
                    success=True,
                    status="RESTOCKED",
                    table_id=plan.get("table_id"),
                    seed=plan.get("seed"),
                    definition_id=str(created[0].get("definition_id", "")),
                    quantity=sum(
                        max(1, int(row.get("quantity", 1))) for row in created
                    ),
                )
            except (KeyError, TypeError, ValueError, OverflowError):
                for created_id in created_ids:
                    self._item_instances.pop(created_id, None)
                self._item_counter = item_counter_backup
                person.clear()
                person.update(person_backup)
                account.clear()
                account.update(account_backup)
                continue

            created_ids = [str(row.get("instance_id", "")) for row in created]
            identity_contract.record_memory(
                self._individual_state,
                identity_id,
                "VENDOR_RESTOCK",
                str(vendor_id),
                self._sim_time,
                text=f"Restocked {len(created)} physical item(s) for the stall.",
                weight=0.58,
            )
            self._append_event_locked(
                "VENDOR_DECISION",
                (
                    f"{vendor_id} chose {recorded_decision.get('focus_definition_id', '')} "
                    "for physical restock."
                ),
                actor_id=identity_id,
                subject_id="RESTOCK",
                target_id=str(vendor_id),
                payload={
                    "vendor_id": str(vendor_id),
                    "npc_id": identity_id,
                    "decision": recorded_decision,
                    "stock_count": stock_count,
                },
            )
            self._append_event_locked(
                "VENDOR_RESTOCK",
                f"{vendor_id} restocked {len(created)} physical item(s).",
                actor_id=identity_id,
                subject_id="RESTOCK",
                target_id=str(vendor_id),
                payload={
                    "vendor_id": str(vendor_id),
                    "npc_id": identity_id,
                    "instance_ids": created_ids,
                    "definition_ids": [
                        str(row.get("definition_id", "")) for row in created
                    ],
                    "quantities": [
                        max(1, int(row.get("quantity", 1))) for row in created
                    ],
                    "table_id": str(plan.get("table_id", "")),
                    "seed": int(plan.get("seed", 0)),
                    "decision": recorded_decision,
                    "restock": restock,
                    "atomic": True,
                },
            )

    def _individual_world_positions_locked(
        self,
        active_ids: list[str],
    ) -> dict[str, tuple[float, float]]:
        """Resolve physical NPC and ambient proxy positions for world actions."""
        wanted = {str(value) for value in active_ids if str(value)}
        positions: dict[str, tuple[float, float]] = {}
        for index in self._npc_indices:
            if not self._alive[index]:
                continue
            identity_id = self._npc_ids[index]
            if identity_id in wanted:
                positions[identity_id] = (self._x[index], self._z[index])
        if len(positions) < len(wanted):
            ambient_rows = life_contract.proxy_rows(
                self._life_spawns,
                self._sim_time,
                player_x=self._x[0],
                player_z=self._z[0],
                terrain_height=self._terrain_height_locked,
            )
            for row in ambient_rows:
                if not isinstance(row, dict):
                    continue
                identity_id = str(row.get("id", ""))
                if identity_id in wanted and identity_id not in positions:
                    positions[identity_id] = (
                        _clamp(row.get("x"), -1000000.0, 1000000.0),
                        _clamp(row.get("z"), -1000000.0, 1000000.0),
                    )
        return positions

    def _world_item_position_locked(
        self,
        item: dict[str, Any],
    ) -> tuple[float, float]:
        position = item.get("position", {})
        if str(item.get("location")) == "CONTAINER":
            container = self._item_instances.get(str(item.get("container_id", "")))
            if isinstance(container, dict):
                position = container.get("position", position)
        if not isinstance(position, dict):
            position = {}
        return (
            _clamp(position.get("x"), -1000000.0, 1000000.0),
            _clamp(position.get("z"), -1000000.0, 1000000.0),
        )

    def _world_target_locked(
        self,
        target_id: str,
        target_hint: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Resolve an identity target against current authoritative world rows."""
        wanted = str(target_id or "")
        if wanted == "player":
            return {
                "id": "player",
                "kind": "PLAYER",
                "x": self._x[0],
                "z": self._z[0],
            }
        item = self._item_instances.get(wanted)
        if isinstance(item, dict):
            definition = item_state.definition(
                self._item_catalog,
                item.get("definition_id"),
            ) or {}
            x, z = self._world_item_position_locked(item)
            return {
                "id": wanted,
                "kind": str(item.get("kind", "ITEM")).upper(),
                "definition_id": str(item.get("definition_id", "")),
                "tags": list(definition.get("tags", []))[:8]
                if isinstance(definition, dict)
                else [],
                "x": x,
                "z": z,
                "location": str(item.get("location", "")),
                "container_id": str(item.get("container_id", "")),
            }
        for station in gear_contract.world_stations(self._gear_tables):
            if isinstance(station, dict) and str(station.get("id")) == wanted:
                return {
                    "id": wanted,
                    "kind": "STATION",
                    "tags": list(station.get("tags", []))[:8],
                    "x": _clamp(station.get("x"), -1000000.0, 1000000.0),
                    "z": _clamp(station.get("z"), -1000000.0, 1000000.0),
                }
        if isinstance(target_hint, dict) and wanted:
            return {
                "id": wanted,
                "kind": str(target_hint.get("kind", "WORLD")).upper(),
                "x": _clamp(target_hint.get("x"), -1000000.0, 1000000.0),
                "z": _clamp(target_hint.get("z"), -1000000.0, 1000000.0),
            }
        return None

    def _npc_action_ready_locked(
        self,
        person: dict[str, Any],
        action: str,
        target_id: str,
    ) -> bool:
        last = person.get("world_action")
        if not isinstance(last, dict):
            return True
        if (
            str(last.get("last_action", "")) != action
            or str(last.get("target_id", "")) != target_id
        ):
            return True
        elapsed = self._sim_time - _clamp(
            last.get("time_s"),
            0.0,
            1000000.0,
        )
        return elapsed >= NPC_WORLD_ACTION_COOLDOWN_S

    def _npc_record_world_action_locked(
        self,
        identity_id: str,
        person: dict[str, Any],
        action: str,
        target_id: str,
        status: str,
        text: str,
        payload: dict[str, Any] | None = None,
    ) -> bool:
        action_state = identity_contract.record_world_action(
            self._individual_state,
            identity_id,
            action,
            target_id,
            self._sim_time,
            status=status,
            text=text,
        )
        if not isinstance(action_state, dict):
            return False
        event_payload = copy.deepcopy(payload or {})
        event_payload.update(
            {
                "status": status,
                "action_count": action_state.get("count", 0),
            }
        )
        progression_state = person.get("progression")
        if not isinstance(progression_state, dict):
            progression_state = npc_progression.starter_state(
                identity_id,
                role=person.get("role"),
                archetype=person.get("archetype"),
                occupation=person.get("occupation"),
            )
            person["progression"] = progression_state
        progression_result = npc_progression.apply_world_action(
            progression_state,
            action_state,
            payload=event_payload,
            sim_time=self._sim_time,
        )
        ascension_result: dict[str, Any] = {}
        if (
            max(1, int(progression_state.get("level", 1))) >= npc_progression.MAX_LEVEL
            and int(progression_state.get("paragon", 0)) >= npc_progression.ASCENSION_PARAGON_COST
        ):
            ascended, ascension_result = npc_progression.ascend(
                progression_state,
                source="NPC_AUTO_ASCENSION",
                sim_time=self._sim_time,
            )
            if ascended:
                progression_result["ascension_result"] = ascension_result
        power_result = self._refresh_npc_progression_locked(
            identity_id,
            person,
            source=f"WORLD_{action}",
        )
        event_payload.update(
            {
                "progression": progression_result,
                "power": power_result,
            }
        )
        self._append_event_locked(
            "NPC_WORLD_ACTION",
            f"{identity_id} {action.lower()} {status.lower()}"
            + (f" at {target_id}." if target_id else "."),
            actor_id=identity_id,
            subject_id=action,
            target_id=target_id,
            payload=event_payload,
        )
        if (
            progression_result.get("xp_gained", 0)
            or progression_result.get("level_ups", 0)
            or progression_result.get("ascension_result")
        ):
            self._append_event_locked(
                "NPC_PROGRESSION",
                f"{identity_id} reached level {progression_state.get('level', 1)} "
                f"with {progression_result.get('xp_gained', 0)} XP from {action.lower()}.",
                actor_id=identity_id,
                subject_id="PROGRESSION",
                target_id=identity_id,
                payload={
                    "action": action,
                    "progression": copy.deepcopy(progression_result),
                    "state": npc_progression.summary(progression_state),
                },
            )
        if power_result.get("changed"):
            self._append_event_locked(
                "NPC_POWER_CHANGED",
                f"{identity_id} power is now {power_result.get('power_score', 0)} "
                f"(gear {power_result.get('gear_score', 0)}).",
                actor_id=identity_id,
                subject_id="POWER",
                target_id=identity_id,
                payload={
                    "power": power_result,
                    "progression": npc_progression.summary(progression_state),
                },
            )
        return True

    def _npc_add_inventory_ref_locked(
        self,
        person: dict[str, Any],
        definition_id: str,
    ) -> bool:
        inventory = person.get("inventory")
        if not isinstance(inventory, list) or len(inventory) >= identity_contract.MAX_CARRIED_ITEMS:
            return False
        inventory.append(str(definition_id)[:96])
        person["inventory"] = inventory[: identity_contract.MAX_CARRIED_ITEMS]
        return True

    def _remove_container_child_ref_locked(
        self,
        item: dict[str, Any],
    ) -> None:
        container_id = str(item.get("container_id", ""))
        container = self._item_instances.get(container_id)
        if not isinstance(container, dict):
            return
        contents = container.get("contents")
        if isinstance(contents, list):
            container["contents"] = [
                value
                for value in contents
                if str(value) != str(item.get("instance_id", ""))
            ][: item_state.MAX_CONTAINER_ITEMS]

    def _npc_move_item_to_pocket_locked(
        self,
        identity_id: str,
        person: dict[str, Any],
        item: dict[str, Any],
    ) -> tuple[bool, dict[str, Any]]:
        if not self._instance_item_visible_locked(item):return False,{'error':'NPC_ITEM_NOT_REACHABLE'}
        if str(item.get("location")) not in {"GROUND", "CONTAINER"}:
            return False, {"error": "NPC_ITEM_NOT_REACHABLE"}
        inventory = person.get("inventory")
        if not isinstance(inventory, list) or len(inventory) >= identity_contract.MAX_CARRIED_ITEMS:
            return False, {"error": "NPC_INVENTORY_FULL"}
        if sum(
            1
            for row in self._item_instances.values()
            if isinstance(row, dict) and str(row.get("location")) == "POCKET"
        ) >= item_state.MAX_POCKET_ITEMS:
            return False, {"error": "NPC_POCKET_BUDGET"}
        self._remove_container_child_ref_locked(item)
        ok, transition = item_state.transition_instance(
            item,
            "POCKET",
            owner_id=identity_id,
        )
        if not ok:
            return False, transition
        if not self._npc_add_inventory_ref_locked(
            person,
            str(item.get("definition_id", "")),
        ):
            # The capacity check above makes this unreachable, but retaining a
            # rollback keeps the transition atomic if the contract changes.
            item_state.transition_instance(item, "GROUND", owner_id="")
            return False, {"error": "NPC_INVENTORY_FULL"}
        return True, {
            "instance_id": str(item.get("instance_id", "")),
            "definition_id": str(item.get("definition_id", "")),
            "name": str(item.get("name", "item")),
        }

    def _npc_consume_item_locked(
        self,
        item: dict[str, Any],
    ) -> tuple[bool, dict[str, Any]]:
        if not self._instance_item_visible_locked(item):return False,{'error':'NPC_ITEM_NOT_REACHABLE'}
        if str(item.get("location")) not in {"GROUND", "CONTAINER"}:
            return False, {"error": "NPC_ITEM_NOT_CONSUMABLE_HERE"}
        self._remove_container_child_ref_locked(item)
        quantity = max(1, int(item.get("quantity", 1)))
        if quantity > 1:
            item["quantity"] = quantity - 1
        else:
            ok, transition = item_state.transition_instance(
                item,
                "DESTROYED",
                owner_id="",
            )
            if not ok:
                return False, transition
            self._item_instances.pop(str(item.get("instance_id", "")), None)
        return True, {
            "instance_id": str(item.get("instance_id", "")),
            "definition_id": str(item.get("definition_id", "")),
            "name": str(item.get("name", "item")),
        }

    def _npc_craft_at_station_locked(
        self,
        identity_id: str,
        person: dict[str, Any],
        station_id: str,
    ) -> tuple[bool, dict[str, Any]]:
        recipes = self._gear_tables.get("recipes", {})
        if not isinstance(recipes, dict):
            return False, {"error": "NPC_RECIPE_TABLE_MISSING"}
        inventory = person.get("inventory")
        if not isinstance(inventory, list):
            return False, {"error": "NPC_INVENTORY_MISSING"}
        # Identity edits and restored content can arrive as references first;
        # bind them before the recipe preflight so crafting never consumes a
        # textual item that has no canonical instance behind it.
        self._materialize_npc_item_instances_locked()
        counts: dict[str, int] = {}
        for value in inventory:
            key = str(value)
            counts[key] = counts.get(key, 0) + 1
        for recipe_id in sorted(recipes):
            recipe = recipes.get(recipe_id)
            if not isinstance(recipe, dict) or str(recipe.get("station_id", "")) != station_id:
                continue
            inputs = recipe.get("inputs", {})
            output = recipe.get("output", {})
            if not isinstance(inputs, dict) or not isinstance(output, dict):
                continue
            if any(
                counts.get(str(item_id), 0) < max(1, int(amount))
                for item_id, amount in inputs.items()
            ):
                continue
            output_slots = sum(max(1, int(amount)) for amount in output.values())
            input_slots = sum(max(1, int(amount)) for amount in inputs.values())
            if len(inventory) - input_slots + output_slots > identity_contract.MAX_CARRIED_ITEMS:
                return False, {"error": "NPC_INVENTORY_FULL", "recipe_id": recipe_id}
            if len(self._item_instances) - input_slots + output_slots > item_state.MAX_WORLD_INSTANCES:
                return False, {"error": "NPC_WORLD_ITEM_BUDGET", "recipe_id": recipe_id}
            for item_id, amount in inputs.items():
                required = max(1, int(amount))
                available_instances = sum(
                    max(1, int(row.get("quantity", 1)))
                    for row in self._item_instances.values()
                    if isinstance(row, dict)
                    and str(row.get("owner_id", "")) == str(identity_id)
                    and str(row.get("location", "")) in {"POCKET", "EQUIPPED"}
                    and str(row.get("definition_id", "")) == str(item_id)
                )
                if available_instances < required:
                    return False, {
                        "error": "NPC_ITEM_INSTANCE_MISSING",
                        "recipe_id": recipe_id,
                        "item_id": str(item_id),
                    }
            if any(
                item_state.definition(self._item_catalog, str(item_id)) is None
                for item_id in output
            ):
                return False, {"error": "NPC_OUTPUT_DEFINITION_MISSING", "recipe_id": recipe_id}
            local_counts = dict(counts)
            profession = str(recipe.get("profession", "SURVIVAL")).upper()
            progression_state = person.get("progression", {})
            ok, result = gear_contract.craft(
                self._gear_tables,
                str(recipe_id),
                local_counts,
                station_id=station_id,
                profession_level=npc_progression.profession_level(
                    progression_state if isinstance(progression_state, dict) else {},
                    profession,
                ),
            )
            if not ok:
                return False, result
            inventory_backup = list(inventory)
            instances_backup = copy.deepcopy(self._item_instances)
            item_counter_backup = self._item_counter
            output_instances: list[str] = []
            try:
                for item_id, amount in inputs.items():
                    remaining = max(1, int(amount))
                    while remaining:
                        if not self._npc_remove_inventory_ref_locked(person, str(item_id)):
                            raise ValueError("NPC_INVENTORY_INPUT_MISSING")
                        if not self._npc_remove_owned_instance_locked(identity_id, str(item_id)):
                            raise ValueError("NPC_ITEM_INSTANCE_MISSING")
                        remaining -= 1
                for item_id, amount in output.items():
                    for _ in range(max(1, int(amount))):
                        inventory.append(str(item_id))
                        created = self._npc_add_item_instance_locked(
                            identity_id,
                            str(item_id),
                            location="POCKET",
                        )
                        if created is None:
                            raise ValueError("NPC_WORLD_ITEM_BUDGET")
                        created["craft_quality"] = str(result.get("quality", "STANDARD"))
                        gear_state = created.get("gear")
                        if isinstance(gear_state, dict):
                            gear_state["quality"] = str(result.get("quality", "STANDARD"))
                            gear_contract.recalculate_gear(gear_state, self._gear_tables)
                        output_instances.append(str(created.get("instance_id", "")))
            except ValueError as exc:
                self._item_instances = instances_backup
                self._item_counter = item_counter_backup
                person["inventory"] = inventory_backup
                return False, {"error": str(exc), "recipe_id": recipe_id}
            person["inventory"] = inventory[: identity_contract.MAX_CARRIED_ITEMS]
            return True, {
                "recipe_id": str(recipe_id),
                "output": copy.deepcopy(output),
                "quality": result.get("quality", "STANDARD"),
                "profession": str(result.get("profession", profession)).upper(),
                "profession_level": max(1, int(result.get("profession_level", 1))),
                "instance_ids": output_instances,
            }
        return False, {"error": "NPC_RECIPE_RESOURCES_MISSING", "station_id": station_id}

    def _execute_npc_world_action_locked(
        self,
        identity_id: str,
        person: dict[str, Any],
        position: tuple[float, float],
    ) -> bool:
        action = str(person.get("activity", person.get("action", "WANDER"))).upper()
        if action in {"WANDER", "FLEE"}:
            return False
        target_hint = person.get("target")
        target_hint = target_hint if isinstance(target_hint, dict) else {}
        target_id = str(target_hint.get("id", ""))
        target = self._world_target_locked(target_id, target_hint)
        if not target:
            return False
        if not self._npc_action_ready_locked(person, action, target_id):
            return False
        distance = math.hypot(
            _clamp(target.get("x"), -1000000.0, 1000000.0) - position[0],
            _clamp(target.get("z"), -1000000.0, 1000000.0) - position[1],
        )
        if distance > NPC_WORLD_ACTION_RADIUS_M:
            return False

        payload: dict[str, Any] = {"distance_m": round(distance, 3)}
        if action == "OBSERVE_PLAYER" and target_id == "player":
            person["relationship_to_player"] = round(
                _clamp(
                    float(person.get("relationship_to_player", 0.0)) + 0.01,
                    -1.0,
                    1.0,
                ),
                4,
            )
            identity_contract.record_memory(
                self._individual_state,
                identity_id,
                "PLAYER_SEEN",
                "player",
                self._sim_time,
                text="Observed player at close range",
                weight=0.7,
            )
            return self._npc_record_world_action_locked(
                identity_id,
                person,
                action,
                target_id,
                "OBSERVED",
                "Observed the player nearby.",
                payload,
            )
        if action == "REST":
            needs = person.setdefault("needs", {})
            needs["fatigue"] = round(
                max(0.0, _clamp(needs.get("fatigue"), 0.0, 1.0) - 0.18),
                4,
            )
            return self._npc_record_world_action_locked(
                identity_id,
                person,
                action,
                target_id,
                "RESTED",
                "Recovered fatigue at home.",
                payload,
            )
        if action == "INSPECT_LOOT":
            payload.update(
                {
                    "kind": target.get("kind", "WORLD"),
                    "definition_id": target.get("definition_id", ""),
                }
            )
            item = self._item_instances.get(target_id)
            collected = item if isinstance(item, dict) else None
            if isinstance(collected, dict) and str(collected.get("kind", "")).upper() == "CONTAINER":
                children = [
                    row
                    for row in self._item_instances.values()
                    if isinstance(row, dict)
                    and str(row.get("location", "")) == "CONTAINER"
                    and str(row.get("container_id", "")) == target_id
                ]
                children.sort(
                    key=lambda row: (
                        -npc_progression.item_score(row),
                        -max(1, int(row.get("level", 1))),
                        str(row.get("instance_id", "")),
                    )
                )
                collected = children[0] if children else None
                if isinstance(item, dict):
                    item["container_state"] = "OPEN"
            if isinstance(collected, dict) and str(collected.get("location", "")) == "CONTAINER":
                container = self._item_instances.get(str(collected.get("container_id", "")))
                if isinstance(container, dict):
                    container["container_state"] = "OPEN"
            if isinstance(collected, dict):
                ok, result = self._npc_move_item_to_pocket_locked(
                    identity_id,
                    person,
                    collected,
                )
                if not ok:
                    return self._npc_record_world_action_locked(
                        identity_id,
                        person,
                        action,
                        target_id,
                        "BLOCKED",
                        "Could not secure the inspected loot.",
                        {**payload, **result},
                    )
                payload.update(result)
                payload["definition_id"] = str(collected.get("definition_id", ""))
                upgraded, gear_result = self._npc_equip_better_gear_locked(
                    identity_id,
                    person,
                    collected,
                )
                if upgraded:
                    payload["gear_upgrade"] = True
                    payload["gear_decision"] = gear_result
                    return self._npc_record_world_action_locked(
                        identity_id,
                        person,
                        action,
                        target_id,
                        "EQUIPPED",
                        f"Found and equipped {collected.get('name', 'gear')}.",
                        payload,
                    )
                payload["gear_decision"] = gear_result
                return self._npc_record_world_action_locked(
                    identity_id,
                    person,
                    action,
                    target_id,
                    "LOOTED" if str(target.get("kind", "")).upper() == "CONTAINER" else "INSPECTED",
                    f"Secured {collected.get('name', 'item')} while searching for better gear.",
                    payload,
                )
            if str(target.get("kind", "")).upper() == "CONTAINER":
                payload["container_state"] = "OPEN"
            return self._npc_record_world_action_locked(
                identity_id,
                person,
                action,
                target_id,
                "INSPECTED" if action == "INSPECT_LOOT" else "ARRIVED",
                f"Reached {target_id} while {action.lower()}.",
                payload,
            )
        if action == "EXPLORE":
            payload.update(
                {
                    "kind": target.get("kind", "WORLD"),
                    "definition_id": target.get("definition_id", ""),
                }
            )
            return self._npc_record_world_action_locked(
                identity_id,
                person,
                action,
                target_id,
                "ARRIVED",
                f"Reached {target_id} while exploring.",
                payload,
            )
        if action in {"GATHER", "HAUL"}:
            item = self._item_instances.get(target_id)
            if action == "HAUL":
                children = [
                    row
                    for row in self._item_instances.values()
                    if isinstance(row, dict)
                    and str(row.get("location")) == "CONTAINER"
                    and str(row.get("container_id")) == target_id
                ]
                item = sorted(
                    children,
                    key=lambda row: str(row.get("instance_id", "")),
                )[0] if children else None
            if not isinstance(item, dict):
                return self._npc_record_world_action_locked(
                    identity_id,
                    person,
                    action,
                    target_id,
                    "BLOCKED",
                    "No reachable item remained.",
                    {**payload, "error": "NPC_ITEM_NOT_FOUND"},
                )
            ok, result = self._npc_move_item_to_pocket_locked(
                identity_id,
                person,
                item,
            )
            if not ok:
                return self._npc_record_world_action_locked(
                    identity_id,
                    person,
                    action,
                    target_id,
                    "BLOCKED",
                    f"Could not {action.lower()} the target.",
                    {**payload, **result},
                )
            return self._npc_record_world_action_locked(
                identity_id,
                person,
                action,
                target_id,
                "COMMITTED",
                f"{action.title()}ed {result.get('name', 'item')}.",
                {**payload, **result},
            )
        if action == "SEEK_FOOD":
            item = self._item_instances.get(target_id)
            if not isinstance(item, dict):
                return False
            tags = {str(value).upper() for value in target.get("tags", [])}
            if "FOOD" not in tags:
                return False
            ok, result = self._npc_consume_item_locked(item)
            if not ok:
                return self._npc_record_world_action_locked(
                    identity_id,
                    person,
                    action,
                    target_id,
                    "BLOCKED",
                    "Food was not consumable at the target.",
                    {**payload, **result},
                )
            needs = person.setdefault("needs", {})
            needs["hunger"] = round(
                max(0.0, _clamp(needs.get("hunger"), 0.0, 1.0) - 0.35),
                4,
            )
            return self._npc_record_world_action_locked(
                identity_id,
                person,
                action,
                target_id,
                "CONSUMED",
                f"Consumed {result.get('name', 'food')}.",
                {**payload, **result},
            )
        if action == "SEEK_WATER":
            tags = {str(value).upper() for value in target.get("tags", [])}
            if not tags.intersection({"WATER", "COOKING"}):
                return False
            needs = person.setdefault("needs", {})
            needs["thirst"] = round(
                max(0.0, _clamp(needs.get("thirst"), 0.0, 1.0) - 0.3),
                4,
            )
            return self._npc_record_world_action_locked(
                identity_id,
                person,
                action,
                target_id,
                "REFILLED",
                "Refilled water at the survival station.",
                payload,
            )
        if action == "CRAFT" and str(target.get("kind")) == "STATION":
            ok, result = self._npc_craft_at_station_locked(
                identity_id,
                person,
                target_id,
            )
            if not ok:
                return self._npc_record_world_action_locked(
                    identity_id,
                    person,
                    action,
                    target_id,
                    "BLOCKED",
                    "Crafting was blocked by the NPC inventory or recipe table.",
                    {**payload, **result},
                )
            progression_state = person.get("progression")
            if not isinstance(progression_state, dict):
                progression_state = npc_progression.starter_state(
                    identity_id,
                    role=person.get("role"),
                    archetype=person.get("archetype"),
                    occupation=person.get("occupation"),
                )
                person["progression"] = progression_state
            result["profession_progression"] = npc_progression.grant_profession_xp(
                progression_state,
                result.get("profession", "SURVIVAL"),
                20,
                sim_time=self._sim_time,
            )
            gear_upgrades: list[dict[str, Any]] = []
            for instance_id in result.get("instance_ids", [])[: identity_contract.MAX_CARRIED_ITEMS]:
                crafted_item = self._item_instances.get(str(instance_id))
                if not isinstance(crafted_item, dict):
                    continue
                upgraded, gear_result = self._npc_equip_better_gear_locked(
                    identity_id,
                    person,
                    crafted_item,
                )
                if upgraded:
                    gear_upgrades.append(gear_result)
            if gear_upgrades:
                result["gear_upgrades"] = gear_upgrades
                result["gear_upgrade"] = True
            needs = person.setdefault("needs", {})
            needs["fatigue"] = round(
                min(1.0, _clamp(needs.get("fatigue"), 0.0, 1.0) + 0.04),
                4,
            )
            return self._npc_record_world_action_locked(
                identity_id,
                person,
                action,
                target_id,
                "COMMITTED",
                f"Crafted {result.get('recipe_id', 'recipe')} at the station.",
                {**payload, **result},
            )
        return False

    def _spawn_particle_locked(
        self,
        x: float,
        y: float,
        z: float,
        vx: float,
        vy: float,
        vz: float,
        life: float,
        color: str,
        owner: str = '',
    ) -> None:
        slot = None
        for offset in range(MAX_PARTICLES):
            candidate = (self._particle_cursor + offset) % MAX_PARTICLES
            if self._plife[candidate] <= 0.0:
                slot = candidate
                break
        if slot is None:
            slot = self._particle_cursor
        else:
            self._particle_count += 1
            bisect.insort(self._active_particle_indices, slot)
        self._particle_cursor = (slot + 1) % MAX_PARTICLES
        self._plife[slot] = float(life)
        self._px[slot] = float(x)
        self._py[slot] = float(y)
        self._pz[slot] = float(z)
        self._pvx[slot] = float(vx)
        self._pvy[slot] = float(vy)
        self._pvz[slot] = float(vz)
        self._pcolor[slot] = str(color)
        self._ride_particle_birth_locked(slot,owner)

    def _burst_locked(self, x: float, y: float, z: float, count: int = 32, *, owner: str = '') -> None:
        count = max(1, min(96, int(count)))
        for index in range(count):
            phase = (index / float(count)) * math.tau
            speed = 3.5 + float(index % 7) * 0.55
            self._spawn_particle_locked(
                x,
                y,
                z,
                math.cos(phase) * speed,
                3.0 + float(index % 5) * 0.7,
                math.sin(phase) * speed,
                0.55 + float(index % 4) * 0.11,
                "#c8a97e" if index % 3 else "#c98989",
                owner=owner,
            )
        self._append_event_locked("PARTICLE_BURST", f"{count} pooled debris particles emitted.")

    def _set_replay_input_locked(self) -> None:
        if not self._replaying:
            return
        if self._replay_index >= len(self._replay_inputs):
            self._replaying = False
            self._running = False
            self._append_event_locked("REPLAY_DONE", "Deterministic replay reached its end.")
            return
        row = self._replay_inputs[self._replay_index]
        self._replay_index += 1
        self._input = {
            "throttle": _clamp(row.get("throttle"), -1.0, 1.0),
            "steer": _clamp(row.get("turn", row.get("steer")), -1.0, 1.0),
            "turn": _clamp(row.get("turn", row.get("steer")), -1.0, 1.0),
            "brake": _clamp(row.get("brake"), 0.0, 1.0),
            "boost": bool(row.get("boost")),
            "forward": _clamp(row.get("forward", row.get("throttle")), -1.0, 1.0),
            "strafe": _clamp(row.get("strafe"), -1.0, 1.0),
            "vertical": _clamp(row.get("vertical"), -1.0, 1.0),
            "jump": bool(row.get("jump")),
            "grapple": bool(row.get("grapple")),
            "movement_mode": world.normalize_movement_mode(
                row.get("movement_mode"), self._movement_mode
            ),
            "mouse_look": bool(row.get("mouse_look")),
            "facing_yaw": _clamp(row.get("facing_yaw"), -180.0, 180.0),
            "camera_yaw": _clamp(row.get("camera_yaw"), -360.0, 360.0),
            "camera_pitch": _clamp(row.get("camera_pitch"), -75.0, 75.0, -8.0),
            "camera_distance": _clamp(
                row.get("camera_distance"),
                2.0,
                160.0,
                world.DEFAULT_CAMERA_DISTANCE_M,
            ),
            "ability_1": bool(row.get("ability_1")),
            "ability_2": bool(row.get("ability_2")),
            "ability_3": bool(row.get("ability_3")),
        }
        if self._input["mouse_look"]:
            self._yaw[0] = math.radians(self._input["facing_yaw"])
        if self._player_defeated_locked():self._input["movement_mode"]='GROUND'
        self._movement_mode = self._input["movement_mode"]
        self._camera_yaw = self._input["camera_yaw"]
        self._camera_pitch = self._input["camera_pitch"]
        self._camera_distance = self._input["camera_distance"]

    def _grapple_detach_locked(self, reason: str = "PLAYER_RELEASE") -> None:
        if self._grapple_anchor is None:
            return
        self._grapple_anchor = None
        self._grapple_rope_length = 0.0
        self._append_event_locked(
            "GRAPPLE_RELEASE",
            "Grapple rope released.",
            actor_id="player",
            subject_id=str(reason)[:48],
        )

    def _grapple_find_anchor_locked(self) -> tuple[float, float, float] | None:
        """Find a clear anchor ahead, without changing the player state."""
        attachable = {
            "HOUSE", "WINDMILL", "WATER_WHEEL", "TIDE_BEACON",
            "DOCK", "BRIDGE", "PALM", "ROCK",
        }
        forward_x, forward_z = controller.character_basis(self._yaw[0])["forward"]
        best: tuple[float, tuple[float, float, float], float] | None = None
        source_x, source_y, source_z = self._x[0], self._y[0] + 0.85, self._z[0]
        for index in self._static_entity_indices:
            if not self._alive[index] or self._kind[index] not in attachable:
                continue
            dx = self._x[index] - source_x
            dz = self._z[index] - source_z
            horizontal = math.hypot(dx, dz)
            if horizontal < 2.5 or horizontal > 23.0:
                continue
            alignment = (dx * forward_x + dz * forward_z) / horizontal
            if alignment < 0.28:
                continue
            anchor = (
                self._x[index],
                self._y[index] + max(2.8, abs(self._sy[index]) * 1.8),
                self._z[index],
            )
            distance = math.dist((source_x, source_y, source_z), anchor)
            if distance > 25.0:
                continue
            clear = True
            for step in range(1, 8):
                t = step / 8.0
                test_x = source_x + (anchor[0] - source_x) * t
                test_y = source_y + (anchor[1] - source_y) * t
                test_z = source_z + (anchor[2] - source_z) * t
                if test_y < self._terrain_height_locked(test_x, test_z) + 0.22:
                    clear = False
                    break
                for obstacle in self._static_entity_indices:
                    if (
                        obstacle == index
                        or not self._alive[obstacle]
                        or self._kind[obstacle] not in attachable
                    ):
                        continue
                    half_x = max(0.35, abs(self._sx[obstacle]) * 0.46)
                    half_z = max(0.35, abs(self._sz[obstacle]) * 0.46)
                    obstacle_bottom = self._y[obstacle] - 0.15
                    obstacle_top = self._y[obstacle] + max(
                        1.4, abs(self._sy[obstacle]) * 1.85
                    )
                    if (
                        abs(test_x - self._x[obstacle]) <= half_x
                        and abs(test_z - self._z[obstacle]) <= half_z
                        and obstacle_bottom <= test_y <= obstacle_top
                    ):
                        clear = False
                        break
                if not clear:
                    break
            if not clear:
                continue
            score = distance + (1.0 - alignment) * 7.0
            if best is None or score < best[0]:
                best = (score, anchor, distance)
        if best is None:
            return None
        return best[1]

    def _grapple_fire_locked(self) -> None:
        """Launch a visible hook toward the nearest valid forward anchor."""
        forward_x, forward_z = controller.character_basis(self._yaw[0])["forward"]
        start = (self._x[0], self._y[0] + 0.85, self._z[0])
        anchor = self._grapple_find_anchor_locked()
        target = anchor or (
            start[0] + forward_x * 23.0,
            start[1] + 0.15,
            start[2] + forward_z * 23.0,
        )
        distance = max(0.1, math.dist(start, target))
        duration = max(0.10, min(0.72, distance / 34.0))
        self._grapple_projectile = {
            "start": start,
            "target": target,
            "anchor": anchor,
            "elapsed_s": 0.0,
            "duration_s": duration,
        }
        self._append_event_locked(
            "GRAPPLE_FIRED",
            "Grapple hook launched.",
            actor_id="player",
            payload={"range_m": round(distance, 3), "targetable": anchor is not None},
        )

    def _grapple_cancel_projectile_locked(self, reason: str) -> None:
        if self._grapple_projectile is None:
            return
        self._grapple_projectile = None
        self._append_event_locked(
            "GRAPPLE_CANCEL",
            "Grapple hook flight cancelled.",
            actor_id="player",
            subject_id=str(reason)[:48],
        )

    def _grapple_tick_projectile_locked(self, dt: float) -> None:
        projectile = self._grapple_projectile
        if projectile is None:
            return
        projectile["elapsed_s"] = min(
            float(projectile["duration_s"]),
            float(projectile["elapsed_s"]) + max(0.0, dt),
        )
        if float(projectile["elapsed_s"]) + 1e-8 < float(projectile["duration_s"]):
            return
        self._grapple_projectile = None
        anchor = projectile.get("anchor")
        if (
            isinstance(anchor, tuple)
            and self._movement_mode == "GROUND"
            and self._vehicle_kind == "NONE"
        ):
            self._grapple_attach_locked(anchor)
            return
        self._append_event_locked(
            "GRAPPLE_MISS",
            "Grapple hook reached its range without a valid anchor.",
            actor_id="player",
        )

    def _grapple_projectile_position_locked(self) -> tuple[float, float, float] | None:
        projectile = self._grapple_projectile
        if projectile is None:
            return None
        start = projectile["start"]
        target = projectile["target"]
        duration = max(1.0e-5, float(projectile["duration_s"]))
        alpha = max(0.0, min(1.0, float(projectile["elapsed_s"]) / duration))
        return tuple(
            float(start[axis]) + (float(target[axis]) - float(start[axis])) * alpha
            for axis in range(3)
        )

    def _grapple_attach_locked(self, anchor: tuple[float, float, float]) -> bool:
        """Latch on hook impact and set rope length from the current player root."""
        self._grapple_anchor = anchor
        root_distance = math.dist(
            (self._x[0], self._y[0], self._z[0]),
            anchor,
        )
        self._grapple_rope_length = max(0.25, min(25.0, root_distance))
        self._append_event_locked(
            "GRAPPLE_ATTACH",
            "Grapple attached on impact.",
            actor_id="player",
            payload={"rope_length_m": round(self._grapple_rope_length, 3)},
        )
        return True

    def _grapple_view_locked(self) -> dict[str, Any]:
        projectile_position = self._grapple_projectile_position_locked()
        return {
            "attached": self._grapple_anchor is not None,
            "anchor_x": round(self._grapple_anchor[0], 3) if self._grapple_anchor else 0.0,
            "anchor_y": round(self._grapple_anchor[1], 3) if self._grapple_anchor else 0.0,
            "anchor_z": round(self._grapple_anchor[2], 3) if self._grapple_anchor else 0.0,
            "projectile_active": projectile_position is not None,
            "projectile_x": round(projectile_position[0], 3) if projectile_position else 0.0,
            "projectile_y": round(projectile_position[1], 3) if projectile_position else 0.0,
            "projectile_z": round(projectile_position[2], 3) if projectile_position else 0.0,
            "rope_length_m": round(self._grapple_rope_length, 3),
        }

    def _build_spatial_grid_locked(self) -> dict[tuple[int, int], list[int]]:
        if getattr(self,'_engine_world',None) is not None:return {}
        grid: dict[tuple[int, int], list[int]] = {}
        for index in self._static_entity_indices:
            cell = (
                math.floor(self._x[index] / 2.0),
                math.floor(self._z[index] / 2.0),
            )
            grid.setdefault(cell, []).append(index)
        return grid

    def _activate_ability_locked(self, ability_id: str) -> tuple[bool, dict[str, Any]]:
        ability = self._content.get("abilities", {}).get(str(ability_id))
        if not isinstance(ability, dict):
            self._last_ability_status = "UNKNOWN"
            return False, {"error": "CONTENT_ABILITY_NOT_FOUND", "ability_id": ability_id}
        if ability.get('kind') in ('SPELL','FORM'):
            return self._start_spell_locked(str(ability_id))
        if self._spell_state.get('pending'):
            self._cancel_spell_locked('MOVEMENT_ABILITY')
        if not self._combat_state.get("actors", {}).get("player", {}).get("alive", True):
            self._last_ability_status = "DEFEATED"
            return False, {"error": "COMBAT_PLAYER_DEFEATED", "ability_id": str(ability_id)}
        if self._services.get('taxi_flight'):
            return False, {'error':'TAXI_IN_PROGRESS','ability_id':str(ability_id)}
        cooldown = max(0.0, float(self._ability_cooldowns.get(str(ability_id), 0.0)))
        if cooldown > 0.0:
            self._last_ability_status = "COOLDOWN"
            return False, {
                "error": "ABILITY_ON_COOLDOWN",
                "ability_id": str(ability_id),
                "remaining_s": round(cooldown, 3),
            }
        effect = ability.get("effect", {})
        cost = max(0.0, float(ability.get("resource_cost", 0.0)))
        if self._resource < cost:
            self._last_ability_status = "RESOURCE"
            return False, {
                "error": "ABILITY_RESOURCE_MISSING",
                "ability_id": str(ability_id),
                "required": round(cost, 2),
                "available": round(self._resource, 2),
            }
        impulse = max(0.0, min(40.0, float(effect.get("impulse", 0.0))))
        facing = controller.character_basis(self._yaw[0])
        forward_x, forward_z = facing["forward"]
        self._vx[0] += forward_x * impulse
        self._vz[0] += forward_z * impulse
        if self._movement_mode != "GROUND":
            vertical = _clamp(self._input.get("vertical"), -1.0, 1.0)
            self._vy[0] += (vertical if abs(vertical) > 0.01 else 0.2) * impulse * 0.55
        self._resource = max(0.0, self._resource - cost)
        self._ability_cooldowns[str(ability_id)] = max(
            0.0, float(ability.get("cooldown_s", 0.0))
        )
        self._last_ability = str(ability_id)
        self._last_ability_status = "FIRED"
        self._last_ability_time = self._sim_time
        burst_count = max(1, min(96, int(effect.get("particle_burst", 12))))
        self._burst_locked(self._x[0], self._y[0], self._z[0], burst_count,owner='player')
        self._append_event_locked(
            "ABILITY",
            f"{ability.get('name', ability_id)} fired in {self._movement_mode.lower()} mode.",
        )
        return True, {
            "ability_id": str(ability_id),
            "name": str(ability.get("name", ability_id)),
            "resource": round(self._resource, 2),
            "cooldown_s": round(self._ability_cooldowns[str(ability_id)], 3),
        }

    def _npc_line_of_sight_locked(self, index: int) -> bool:
        """Run a cheap 2D segment-vs-static-circle visibility check."""
        return self._line_of_sight_locked((self._x[index],self._y[index]+.5,self._z[index]),
            (self._x[0],self._y[0]+.5,self._z[0]),ignore_index=index)

    def _line_of_sight_locked(self,start,end,*,ignore_index=None) -> bool:
        """Observe the current world between the two actual combatants."""
        imported=getattr(self,'_engine_world',None)
        if imported is not None:
            return imported.line_of_sight(start,end)
        target_x,target_z=end[0],end[2]
        start_x,start_z=start[0],start[2]
        segment_x = target_x - start_x
        segment_z = target_z - start_z
        segment_length_sq = segment_x * segment_x + segment_z * segment_z
        if segment_length_sq <= 0.0001:
            return True
        for other in self._static_entity_indices:
            if other == ignore_index:
                continue
            obstacle_x = self._x[other]
            obstacle_z = self._z[other]
            projection = (
                (obstacle_x - start_x) * segment_x
                + (obstacle_z - start_z) * segment_z
            ) / segment_length_sq
            if projection <= 0.0 or projection >= 1.0:
                continue
            closest_x = start_x + segment_x * projection
            closest_z = start_z + segment_z * projection
            clearance = max(0.28, self._radius[other] + 0.22)
            if math.hypot(obstacle_x - closest_x, obstacle_z - closest_z) <= clearance:
                return False
        return True

    def _navigation_tiles_for_cells_locked(
        self,
        cells: list[dict[str, Any]],
        movement_mode: str,
    ) -> list[dict[str, Any]]:
        """Build nav only for cells that entered the current interest set."""
        mode = world.normalize_movement_mode(movement_mode)
        override_revision = int(self._terrain_overrides.get("revision", 0))
        cell_coordinates = {
            (int(row.get("x", 0)), int(row.get("z", 0)))
            for row in cells
            if isinstance(row, dict)
        }
        navigation_key = (
            tuple(sorted(cell_coordinates)),
            mode,
            override_revision,
        )
        if navigation_key != self._navigation_cache_key:
            same_terrain = (
                self._navigation_cache_override_revision == override_revision
            )
            if same_terrain:
                retained_cells = self._navigation_cache_cells & cell_coordinates
                retained_keys = {
                    world.cell_key(cell_x, cell_z)
                    for cell_x, cell_z in retained_cells
                }
                retained_tiles = [
                    tile
                    for tile in self._navigation_tiles
                    if str(tile.get("terrain_cell", "")) in retained_keys
                ]
                if self._navigation_cache_mode!=mode:
                    retained_tiles=nav_contract.tiles_for_mode(retained_tiles,mode)
                new_cells = [
                    row
                    for row in cells
                    if isinstance(row, dict)
                    and (int(row.get("x", 0)), int(row.get("z", 0)))
                    not in retained_cells
                ]
            else:
                retained_tiles = []
                new_cells = cells
            rebuilt_tiles = nav_contract.build_nav_tiles(
                new_cells,
                world_seed=WORLD_SEED,
                overrides=self._terrain_overrides,
                movement_mode=mode,
            ) if new_cells else []
            self._navigation_tiles = sorted(
                [*retained_tiles, *rebuilt_tiles],
                key=lambda row: (int(row.get("z", 0)), int(row.get("x", 0))),
            )
            self._navigation_cache_key = navigation_key
            self._navigation_cache_cells = cell_coordinates
            self._navigation_cache_override_revision = override_revision
            self._navigation_cache_mode = mode
        return self._navigation_tiles

    def _ensure_ground_navigation_locked(self) -> list[dict[str, Any]]:
        """Ensure the shared ground tiles exist before an NPC path query."""
        center = (
            world.chunk_coord(self._x[0]),
            world.chunk_coord(self._z[0]),
        )
        if center != self._navigation_interest_center:
            self._navigation_interest_cells = list(
                world.interest_cells(
                    self._x[0],
                    self._z[0],
                    radius=world.DEFAULT_INTEREST_RADIUS,
                )[:MAX_CHUNKS]
            )
            self._navigation_interest_center = center
        return self._navigation_tiles_for_cells_locked(
            self._navigation_interest_cells,
            "GROUND",
        )

    def _plan_npc_path_locked(
        self,
        index: int,
        target_x: float,
        target_z: float,
        desired_speed: float,
    ) -> None:
        """Plan one short route at decision cadence, with direct fallback."""
        if self._movement_mode != "GROUND":
            self._npc_path[index] = []
            self._npc_path_index[index] = 0
            self._npc_path_status[index] = "MODE_DIRECT"
            self._npc_path_goal_tile[index] = None
            self._npc_path_navigation_key[index] = None
            return
        if desired_speed <= 0.0:
            self._npc_path[index] = []
            self._npc_path_index[index] = 0
            self._npc_path_status[index] = "STOPPED"
            self._npc_path_goal_tile[index] = None
            self._npc_path_navigation_key[index] = None
            return
        if getattr(self, '_engine_world', None) is not None:
            # Imported geometry has its own resident floors and hulls. GG's
            # procedural tile cache is not a path through a mounted world.
            self._npc_path[index] = []
            self._npc_path_index[index] = 0
            self._npc_path_status[index] = 'WORLD_WALKING'
            self._npc_path_goal_tile[index] = None
            self._npc_path_navigation_key[index] = None
            return
        tiles = self._ensure_ground_navigation_locked()
        goal_tile = (
            nav_contract.tile_coord(target_x),
            nav_contract.tile_coord(target_z),
        )
        navigation_key = self._navigation_cache_key
        cached_status = self._npc_path_status[index]
        same_route = (
            self._npc_path_goal_tile[index] == goal_tile
            and self._npc_path_navigation_key[index] == navigation_key
        )
        if same_route and cached_status == "READY_AT_TILE":
            return
        if same_route and cached_status == "READY":
            route_is_live = (
                self._npc_path_index[index] < len(self._npc_path[index])
            )
            npc_tile = (
                nav_contract.tile_coord(self._x[index]),
                nav_contract.tile_coord(self._z[index]),
            )
            if route_is_live or npc_tile == goal_tile:
                return
        if (
            same_route
            and cached_status == "NO_PATH_FALLBACK"
            and self._tick - self._npc_path_attempt_tick[index] < FIXED_HZ
        ):
            return

        self._npc_path[index] = []
        self._npc_path_index[index] = 0
        self._npc_path_goal_tile[index] = goal_tile
        self._npc_path_navigation_key[index] = navigation_key
        self._npc_path_attempt_tick[index] = self._tick
        result = nav_contract.plan_path(
            tiles,
            self._x[index],
            self._z[index],
            target_x,
            target_z,
            max_nodes=32,
        )
        waypoints = result.get("waypoints", [])
        if str(result.get("status", "")) != "READY" or not isinstance(waypoints, list):
            self._npc_path_status[index] = "NO_PATH_FALLBACK"
            return
        # The first point is the nearest tile under the NPC.  Store only the
        # future points so the regular steering loop can consume them.
        self._npc_path[index] = [
            {
                "x": float(row.get("x", self._x[index])),
                "z": float(row.get("z", self._z[index])),
            }
            for row in waypoints[1:]
            if isinstance(row, dict)
        ]
        self._npc_path_status[index] = (
            "READY" if self._npc_path[index] else "READY_AT_TILE"
        )

    def _npc_active_target_locked(self, index: int) -> tuple[float, float]:
        """Return the next waypoint, advancing short routes deterministically."""
        path = self._npc_path[index]
        while self._npc_path_index[index] < len(path):
            waypoint = path[self._npc_path_index[index]]
            if math.hypot(
                float(waypoint["x"]) - self._x[index],
                float(waypoint["z"]) - self._z[index],
            ) > 0.55:
                return float(waypoint["x"]), float(waypoint["z"])
            self._npc_path_index[index] += 1
        return self._npc_target_x[index], self._npc_target_z[index]

    def _tick_npcs_locked(self, dt: float) -> None:
        """Advance the bounded NPC pool with cheap steering and perception."""
        if not self._npc_indices:
            return
        decision_tick = self._tick % npc_contract.DECISION_TICKS == 0
        for index in self._npc_indices:
            if not self._alive[index]:
                continue
            combat_actor = self._combat_state.get("actors", {}).get(self._npc_ids[index])
            if isinstance(combat_actor, dict) and not combat_actor.get("alive", True):
                self._vx[index] = 0.0
                self._vz[index] = 0.0
                self._npc_state[index] = "DEAD"
                self._npc_reason[index] = "COMBAT_DEFEATED"
                continue
            mounted = getattr(self, '_engine_world', None)
            swimming = False
            if mounted is not None:
                from backend.game_engine_adapter_locomotion import motion
                position,vertical,mode,impact=motion(mounted,(self._x[index],self._y[index]-.65,self._z[index]),self._vy[index],dt)
                if position[1]!=self._y[index]-.65:self._y[index]=position[1]+.65
                self._vy[index]=vertical;swimming=mode=='SWIM'
                if isinstance(combat_actor,dict) and impact>8:
                    dealt,absorbed=combat_contract.deal_damage(self._combat_state,combat_actor,combat_actor['max_health']*min(1.,(impact-8.)/20.),'environment',self._sim_time)
                    self._start_character_action_locked(self._npc_ids[index],'HitReact' if combat_actor['alive'] else 'Death')
                    self._append_event_locked('NPC_FALL_DAMAGE','NPC landed after falling.',actor_id=self._npc_ids[index],payload=dict(damage=dealt,absorbed=absorbed))
                if mode in ('FALL','HOLD') or isinstance(combat_actor,dict) and not combat_actor.get('alive',True):
                    self._vx[index]=self._vz[index]=0.;self._npc_path_status[index]=mode
                    continue
            archetype = self._npc_archetype[index]
            profile = npc_contract.PROFILES.get(
                archetype,
                npc_contract.PROFILES["WANDERER"],
            )
            self._npc_state_time[index] += dt
            self._npc_last_seen_age[index] = min(
                60.0,
                self._npc_last_seen_age[index] + dt,
            )
            if decision_tick or self._npc_reason[index] == "SPAWN":
                player_distance = math.hypot(
                    self._x[0] - self._x[index],
                    self._z[0] - self._z[index],
                )
                line_of_sight = (
                    player_distance <= profile["sense_radius"]
                    and self._npc_line_of_sight_locked(index)
                )
                if line_of_sight:
                    self._npc_last_seen_x[index] = self._x[0]
                    self._npc_last_seen_z[index] = self._z[0]
                    self._npc_last_seen_age[index] = 0.0
                decision = npc_contract.decide(
                    archetype,
                    self._npc_state[index],
                    self._sim_time,
                    self._x[index],
                    self._z[index],
                    self._npc_home_x[index],
                    self._npc_home_z[index],
                    self._x[0],
                    self._z[0],
                    self._npc_phase[index],
                    line_of_sight,
                    self._npc_last_seen_age[index],
                    self._npc_last_seen_x[index],
                    self._npc_last_seen_z[index],
                )
                decision = self._group_steering_locked(index, decision)
                # Individual world-use decisions are a secondary target seam:
                # player perception still wins, while a calm NPC may walk to
                # a cache or station chosen by its own bounded identity state.
                world_target = identity_contract.target_for(
                    self._individual_state,
                    self._npc_ids[index],
                )
                if (
                    decision.state == "WANDER"
                    and not decision.line_of_sight
                    and isinstance(world_target, dict)
                    and str(world_target.get("kind", "")).upper() != "PLAYER"
                ):
                    target_x = _clamp(
                        world_target.get("x"),
                        -1000000.0,
                        1000000.0,
                        self._npc_home_x[index],
                    )
                    target_z = _clamp(
                        world_target.get("z"),
                        -1000000.0,
                        1000000.0,
                        self._npc_home_z[index],
                    )
                    home_dx = target_x - self._npc_home_x[index]
                    home_dz = target_z - self._npc_home_z[index]
                    home_distance = math.hypot(home_dx, home_dz)
                    if home_distance > profile["wander_radius"]:
                        scale = profile["wander_radius"] / max(home_distance, 0.0001)
                        target_x = self._npc_home_x[index] + home_dx * scale
                        target_z = self._npc_home_z[index] + home_dz * scale
                    decision = decision._replace(
                        target_x=target_x,
                        target_z=target_z,
                        target_distance=math.hypot(
                            target_x - self._x[index],
                            target_z - self._z[index],
                        ),
                        desired_speed=min(profile["speed"], decision.desired_speed),
                        reason=(
                            "WORLD_"
                            + str(
                                self._individual_state.get("individuals", {})
                                .get(self._npc_ids[index], {})
                                .get("action", "USE")
                            )
                        )[:32],
                    )
                previous_state = self._npc_state[index]
                self._npc_state[index] = decision.state
                self._npc_target_x[index] = decision.target_x
                self._npc_target_z[index] = decision.target_z
                self._npc_decision_speed[index] = decision.desired_speed
                self._npc_perception_radius[index] = decision.perception_radius
                self._npc_target_distance[index] = decision.target_distance
                self._npc_reason[index] = decision.reason
                self._npc_line_of_sight[index] = decision.line_of_sight
                self._npc_stimulus[index] = decision.stimulus
                self._plan_npc_path_locked(
                    index,
                    decision.target_x,
                    decision.target_z,
                    decision.desired_speed,
                )
                if previous_state != decision.state:
                    self._npc_state_time[index] = 0.0
                    self._append_event_locked(
                        "NPC_STATE",
                        f"{self._npc_ids[index]}: {previous_state.lower()} -> "
                        f"{decision.state.lower()}.",
                    )

            active_target_x, active_target_z = self._npc_active_target_locked(index)
            target_dx = active_target_x - self._x[index]
            target_dz = active_target_z - self._z[index]
            target_distance = math.hypot(target_dx, target_dz)
            desired_speed = max(
                0.0,
                min(profile["run_speed"], self._npc_decision_speed[index]),
            )
            home_distance = math.hypot(self._x[index]-self._npc_home_x[index],
                                       self._z[index]-self._npc_home_z[index])
            if home_distance > profile['wander_radius'] and self._npc_ids[index] not in self._services['group']['members']:
                # A live actor outside its home area walks back. Projecting
                # its root onto the boundary teleports displaced actors and
                # actors promoted while walking an outer part of a route.
                target_dx = self._npc_home_x[index]-self._x[index]
                target_dz = self._npc_home_z[index]-self._z[index]
                target_distance = home_distance
                desired_speed = profile['speed']
                self._npc_reason[index] = 'HOME_RETURN'
            mounted = getattr(self, '_engine_world', None)
            if mounted is not None:
                from backend.game_engine_adapter_locomotion import routes
                waypoint = routes(mounted).waypoint(str(self._npc_ids[index]),
                    (self._x[index], self._y[index]-.65, self._z[index]),
                    (self._x[index]+target_dx, self._y[index]-.65, self._z[index]+target_dz), self._sim_time,swimming=swimming)
                target_dx, target_dz = waypoint[0]-self._x[index], waypoint[2]-self._z[index]
                target_distance = math.hypot(target_dx, target_dz)
                self._npc_path_status[index] = routes(mounted).last_status
                desired_speed = min(desired_speed, target_distance/max(dt, .0001))
                if target_distance < .01:
                    self._vx[index] = self._vz[index] = 0.
            movement_scale = combat_contract.movement_scale(
                self._combat_state.get("actors", {}).get(str(self._npc_ids[index]), {}),
                self._sim_time)
            desired_speed *= movement_scale
            active_action = self._character_action_for_locked(self._npc_ids[index])
            if active_action.get("clip") in animation_contract.WORLD_INTERACTION_CLIPS:
                desired_speed = 0.
            if target_distance > 0.3 and desired_speed > 0.0:
                desired_vx = target_dx / target_distance * desired_speed
                desired_vz = target_dz / target_distance * desired_speed
            else:
                desired_vx = 0.0
                desired_vz = 0.0
            response = min(1.0, max(0.0, dt * 8.0))
            self._vx[index] += (desired_vx - self._vx[index]) * response
            self._vz[index] += (desired_vz - self._vz[index]) * response
            self._vy[index] = 0.0

            current_speed = math.hypot(self._vx[index], self._vz[index])
            if current_speed > profile["run_speed"] * movement_scale:
                scale = profile["run_speed"] * movement_scale / current_speed
                self._vx[index] *= scale
                self._vz[index] *= scale
            if mounted is not None:
                from backend.game_engine_adapter_locomotion import move
                old_x, old_z = self._x[index], self._z[index]
                nx, ny, nz = move(mounted, (old_x, self._y[index]-.65, old_z),
                    old_x+self._vx[index]*dt, old_z+self._vz[index]*dt,swimming=swimming)
                held = nx == old_x and nz == old_z
                self._x[index], self._y[index], self._z[index] = nx, self._y[index] if held else ny+.65, nz
                self._vx[index], self._vz[index] = (nx-old_x)/max(dt,.0001), (nz-old_z)/max(dt,.0001)
                current_speed = math.hypot(self._vx[index], self._vz[index])
            else:
                self._x[index] += self._vx[index] * dt
                self._z[index] += self._vz[index] * dt
                self._y[index] = self._terrain_height_locked(self._x[index], self._z[index]) + 0.65
            if current_speed > 0.02:
                # Authored Blender characters face +Z at yaw zero. Keep NPC
                # mesh heading aligned with their actual velocity.
                self._yaw[index] = math.atan2(self._vx[index], self._vz[index])

    def _tick_locked(self, dt: float) -> None:
        mounted=getattr(self,'_engine_world',None)
        if getattr(self,'_mounted_world_resume',None) or getattr(mounted,'initial_collision_pending',False):
            return
        started = time.perf_counter()
        self._set_replay_input_locked()
        if self._replaying is False and self._running is False:
            return
        previously_grounded = self._grounded
        previous_vertical_speed = self._vy[0]
        self._tick += 1
        self._sim_time += dt
        self._tick_crafting_locked(dt)
        self._double_jump_pose_remaining_s = max(
            0.0,
            self._double_jump_pose_remaining_s - dt,
        )
        self._collision_cooldown = max(0.0, self._collision_cooldown - dt)
        for ability_id in tuple(self._ability_cooldowns):
            remaining = max(0.0, self._ability_cooldowns[ability_id] - dt)
            if remaining <= 0.0:
                self._ability_cooldowns.pop(ability_id, None)
            else:
                self._ability_cooldowns[ability_id] = remaining
        self._resource = min(100.0, self._resource + 8.0 * dt)

        current_input = self._client_tick_input_locked(self._input)
        grapple_pressed = bool(current_input.get("grapple"))
        grapple_edge = grapple_pressed and not self._grapple_held
        if grapple_edge:
            if self._grapple_anchor is not None:
                self._grapple_detach_locked()
            elif self._grapple_projectile is not None:
                self._grapple_cancel_projectile_locked("PLAYER_RELEASE")
            elif self._movement_mode == "GROUND" and self._vehicle_kind == "NONE":
                self._grapple_fire_locked()
        self._grapple_held = grapple_pressed
        if self._grapple_anchor is not None and (
            self._movement_mode != "GROUND" or self._vehicle_kind == "BOAT"
        ):
            self._grapple_detach_locked("MOVEMENT_MODE_CHANGED")
        if self._grapple_projectile is not None and (
            self._movement_mode != "GROUND" or self._vehicle_kind != "NONE"
        ):
            self._grapple_cancel_projectile_locked("MOVEMENT_MODE_CHANGED")
        self._grapple_tick_projectile_locked(dt)
        if self._recording and len(self._recorded_inputs) < MAX_REPLAY_INPUTS:
            self._recorded_inputs.append({"tick": self._tick, **current_input})

        throttle = _clamp(current_input.get("throttle"), -1.0, 1.0)
        turn_input = _clamp(
            current_input.get("turn", current_input.get("steer")),
            -1.0,
            1.0,
        )
        brake = _clamp(current_input.get("brake"), 0.0, 1.0)
        boost = bool(current_input.get("boost"))
        forward = _clamp(current_input.get("forward", throttle), -1.0, 1.0)
        strafe = _clamp(current_input.get("strafe"), -1.0, 1.0)
        vertical = _clamp(current_input.get("vertical"), -1.0, 1.0)
        ability_inputs = {
            "ability.surge": bool(current_input.get("ability_1")),
            "ability.undertow": bool(current_input.get("ability_2")),
            "ability.sky_leap": bool(current_input.get("ability_3")),
        }
        for ability_id, ability_held in ability_inputs.items():
            if ability_held and not self._ability_held.get(ability_id, False):
                self._activate_ability_locked(ability_id)
            self._ability_held[ability_id] = ability_held

        previous_player_x = self._x[0]
        previous_player_z = self._z[0]
        boat_index = self._boat_entity_index
        if boat_index is not None and self._alive[boat_index]:
            boat_x = self._x[boat_index]
            boat_z = self._z[boat_index]
            water = self._water_sample_locked(boat_x, boat_z)
            if self._vehicle_kind == "BOAT":
                boat_motion = mobility_contract.boat_step(
                    x=boat_x,
                    z=boat_z,
                    yaw=self._yaw[boat_index],
                    vx=self._vx[boat_index],
                    vz=self._vz[boat_index],
                    throttle=forward,
                    turn=turn_input,
                    brake=brake,
                    current_x=water["current_mps"]["x"],
                    current_z=water["current_mps"]["z"],
                    dt=dt,
                )
                ahead_bed = max(
                    0.0,
                    terrain_contract.SEA_LEVEL
                    - self._terrain_height_locked(boat_motion["x"], boat_motion["z"]),
                )
                if ahead_bed < mobility_contract.MIN_BOAT_DEPTH_M:
                    boat_motion["x"] = boat_x
                    boat_motion["z"] = boat_z
                    boat_motion["vx"] = self._vx[boat_index] * 0.25
                    boat_motion["vz"] = self._vz[boat_index] * 0.25
                    boat_motion["speed"] = math.hypot(boat_motion["vx"], boat_motion["vz"])
                self._x[boat_index] = boat_motion["x"]
                self._z[boat_index] = boat_motion["z"]
                self._yaw[boat_index] = boat_motion["yaw"]
                self._vx[boat_index] = boat_motion["vx"]
                self._vz[boat_index] = boat_motion["vz"]
                water = self._water_sample_locked(self._x[boat_index], self._z[boat_index])
                slope = water["slope"]
                if water.get("has_surface", True):
                    self._y[boat_index] = water["height_m"] + mobility_contract.BOAT_HULL_DRAFT_M
                water_pitch, water_roll = mobility_contract.ride_tilt_degrees(
                    self._yaw[boat_index], slope["x"], slope["z"]
                )
                self._pitch[boat_index] = water_pitch
                self._roll[boat_index] = max(
                    -18.0, min(18.0, water_roll + boat_motion["roll"])
                )
                self._x[0] = self._x[boat_index]
                self._z[0] = self._z[boat_index]
                self._y[0] = (
                    self._y[boat_index]
                    + mobility_contract.skiff_seat_offset(self._sy[boat_index])
                )
                self._yaw[0] = self._yaw[boat_index]
                self._vx[0] = self._vx[boat_index]
                self._vy[0] = 0.0
                self._vz[0] = self._vz[boat_index]
                self._grounded = True
                self._jump_count = 0
                self._double_jump_pose_remaining_s = 0.0
                self._sprinting = False
            else:
                slope = water["slope"]
                if water.get("has_surface", True):
                    self._y[boat_index] = water["height_m"] + mobility_contract.BOAT_HULL_DRAFT_M
                self._pitch[boat_index], self._roll[boat_index] = (
                    mobility_contract.ride_tilt_degrees(
                        self._yaw[boat_index], slope["x"], slope["z"]
                    )
                )

        if self._vehicle_kind == "HOVERBOARD":
            predicted_x = self._x[0] + self._vx[0] * dt
            predicted_z = self._z[0] + self._vz[0] * dt
            support_y = self._ground_contact_height_locked(
                predicted_x, predicted_z, vehicle_kind="HOVERBOARD"
            )
            board_motion = mobility_contract.hoverboard_step(
                x=self._x[0],
                z=self._z[0],
                yaw=self._yaw[0],
                vx=self._vx[0],
                vy=self._vy[0],
                vz=self._vz[0],
                forward=forward,
                strafe=strafe,
                turn=turn_input,
                boost=boost,
                jump_pressed=bool(current_input.get("jump")),
                jump_was_pressed=self._jump_held,
                jump_buffer_remaining=self._jump_buffer_remaining_s,
                coyote_remaining=self._coyote_time_remaining_s,
                jump_hold_time=self._jump_hold_time_s,
                jump_count=self._jump_count,
                grounded=self._grounded,
                y=self._y[0],
                ground_y=support_y,
                dt=dt,
            )
            board_x = board_motion["x"]
            board_z = board_motion["z"]
            current_support_y = self._ground_contact_height_locked(
                self._x[0], self._z[0], vehicle_kind="HOVERBOARD"
            )
            board_contact = mobility_contract.ground_surface_contact(
                current_x=self._x[0],
                current_z=self._z[0],
                next_x=board_x,
                next_z=board_z,
                current_ground_y=current_support_y,
                next_ground_y=support_y,
                player_y=board_motion["y"],
                airborne=not board_motion["grounded"],
            )
            if not board_contact["allowed"]:
                x_only = mobility_contract.ground_surface_contact(
                    current_x=self._x[0], current_z=self._z[0],
                    next_x=board_x, next_z=self._z[0],
                    current_ground_y=current_support_y,
                    next_ground_y=self._ground_contact_height_locked(
                        board_x, self._z[0], vehicle_kind="HOVERBOARD"
                    ),
                    player_y=board_motion["y"],
                    airborne=not board_motion["grounded"],
                )["allowed"]
                z_only = mobility_contract.ground_surface_contact(
                    current_x=self._x[0], current_z=self._z[0],
                    next_x=self._x[0], next_z=board_z,
                    current_ground_y=current_support_y,
                    next_ground_y=self._ground_contact_height_locked(
                        self._x[0], board_z, vehicle_kind="HOVERBOARD"
                    ),
                    player_y=board_motion["y"],
                    airborne=not board_motion["grounded"],
                )["allowed"]
                if x_only:
                    board_z = self._z[0]
                    board_motion["vz"] = 0.0
                elif z_only:
                    board_x = self._x[0]
                    board_motion["vx"] = 0.0
                else:
                    board_x = self._x[0]
                    board_z = self._z[0]
                    board_motion["vx"] = 0.0
                    board_motion["vz"] = 0.0
            self._x[0] = board_x
            self._z[0] = board_z
            actual_support_y = self._ground_contact_height_locked(
                self._x[0], self._z[0], vehicle_kind="HOVERBOARD"
            )
            self._vx[0] = board_motion["vx"]
            self._vz[0] = board_motion["vz"]
            self._yaw[0] = board_motion["yaw"]
            on_wave = (
                self._water_depth_locked(self._x[0], self._z[0])
                > mobility_contract.MIN_SWIMMABLE_DEPTH_M
            )
            # A wave can drop faster than gravity. Stick to it until a jump,
            # or the crest passes through a body that is still falling.
            if on_wave and int(board_motion["jump_count"]) == 0:
                self._y[0] = actual_support_y
                self._vy[0] = 0.0
                self._grounded = True
                self._coyote_time_remaining_s = controller.COYOTE_TIME_S
                self._jump_hold_time_s = 0.0
                self._jump_count = 0
            else:
                self._y[0] = max(actual_support_y, board_motion["y"])
                self._vy[0] = board_motion["vy"]
                if self._y[0] <= actual_support_y + 1e-4:
                    self._y[0] = actual_support_y
                    self._vy[0] = 0.0
                    self._grounded = True
                    self._coyote_time_remaining_s = controller.COYOTE_TIME_S
                    self._jump_hold_time_s = 0.0
                    self._jump_count = 0
                else:
                    self._grounded = False
                    self._coyote_time_remaining_s = board_motion["coyote_remaining"]
                    self._jump_hold_time_s = board_motion["jump_hold_time"]
                    self._jump_count = int(board_motion["jump_count"])
            self._jump_buffer_remaining_s = board_motion["jump_buffer_remaining"]
            self._jump_held = bool(current_input.get("jump"))
            if self._grounded and on_wave:
                slope = self._water_sample_locked(self._x[0], self._z[0])["slope"]
                self._pitch[0], self._roll[0] = mobility_contract.ride_tilt_degrees(
                    self._yaw[0], slope["x"], slope["z"]
                )
            else:
                self._pitch[0] = 0.0
                self._roll[0] = 0.0
            if board_motion["double_jumped"]:
                self._double_jump_pose_remaining_s = (
                    animation_contract.DOUBLE_JUMP_ANIMATION_SECONDS
                )
            elif board_motion["grounded"]:
                self._double_jump_pose_remaining_s = 0.0
            self._sprinting = bool(boost and abs(forward) > 0.01)
            if board_motion["jumped"]:
                self._append_event_locked(
                    "BOARD_DOUBLE_JUMP" if board_motion["double_jumped"] else "BOARD_JUMP",
                    "Hoverboard air-jump impulse applied."
                    if board_motion["double_jumped"]
                    else "Hoverboard jump impulse applied.",
                )
        elif (
            self._grapple_anchor is not None
            and self._vehicle_kind == "NONE"
            and self._movement_mode == "GROUND"
        ):
            # While tethered, use low-drag air control and gravity. Ground
            # friction/landing code would erase the momentum that makes the
            # rope behave like a pendulum.
            self._yaw[0] = (
                self._yaw[0] + turn_input * controller.TURN_SPEED_RADPS * dt + math.pi
            ) % math.tau - math.pi
            air_drag = max(0.0, 1.0 - (0.16 + brake * 2.0) * dt)
            self._vx[0] *= air_drag
            self._vz[0] *= air_drag
            self._vy[0] -= controller.GRAVITY_MPS2 * dt
            self._x[0] += self._vx[0] * dt
            self._y[0] += self._vy[0] * dt
            self._z[0] += self._vz[0] * dt
            self._grounded = False
            self._jump_held = bool(current_input.get("jump"))
            self._sprinting = False
        elif self._vehicle_kind != "BOAT" and self._movement_mode == "GROUND":
            motion = controller.ground_step(
                camera_yaw=self._camera_yaw,
                character_yaw=self._yaw[0],
                forward=forward,
                strafe=strafe,
                turn_input=turn_input,
                boost=boost,
                current_vx=self._vx[0],
                current_vz=self._vz[0],
                current_yaw=self._yaw[0],
                dt=dt,
            )
            self._vx[0] = motion["vx"]
            self._vz[0] = motion["vz"]
            self._yaw[0] = motion["yaw"]
            self._sprinting = bool(motion["sprinting"])
            ground_y = self._ground_contact_height_locked(self._x[0], self._z[0])
            vertical_motion = controller.vertical_step(
                y=self._y[0],
                vertical_velocity=self._vy[0],
                ground_y=ground_y,
                jump_pressed=bool(current_input.get("jump")),
                jump_was_pressed=self._jump_held,
                coyote_remaining=self._coyote_time_remaining_s,
                jump_buffer_remaining=self._jump_buffer_remaining_s,
                jump_hold_time=self._jump_hold_time_s,
                jump_count=self._jump_count,
                dt=dt,
            )
            self._y[0] = vertical_motion["y"]
            self._vy[0] = vertical_motion["vertical_velocity"]
            self._grounded = bool(vertical_motion["grounded"])
            self._coyote_time_remaining_s = float(vertical_motion["coyote_remaining"])
            self._jump_buffer_remaining_s = float(vertical_motion["jump_buffer_remaining"])
            self._jump_hold_time_s = float(vertical_motion["jump_hold_time"])
            self._jump_count = int(vertical_motion["jump_count"])
            if vertical_motion["double_jumped"]:
                self._double_jump_pose_remaining_s = (
                    animation_contract.DOUBLE_JUMP_ANIMATION_SECONDS
                )
            elif vertical_motion["grounded"]:
                self._double_jump_pose_remaining_s = 0.0
            if vertical_motion["jumped"]:
                self._append_event_locked(
                    "DOUBLE_JUMP" if vertical_motion["double_jumped"] else "JUMP",
                    "Second jump impulse applied in air."
                    if vertical_motion["double_jumped"]
                    else "Player jump impulse applied.",
                )
            self._jump_held = bool(current_input.get("jump"))
            candidate_x = self._x[0] + self._vx[0] * dt
            candidate_z = self._z[0] + self._vz[0] * dt
            candidate_ground_y = self._ground_contact_height_locked(candidate_x, candidate_z)
            contact = mobility_contract.ground_surface_contact(
                current_x=self._x[0],
                current_z=self._z[0],
                next_x=candidate_x,
                next_z=candidate_z,
                current_ground_y=ground_y,
                next_ground_y=candidate_ground_y,
                player_y=self._y[0],
                airborne=not self._grounded,
            )
            if contact["allowed"]:
                self._x[0] = candidate_x
                self._z[0] = candidate_z
            else:
                x_only = mobility_contract.ground_surface_contact(
                    current_x=self._x[0], current_z=self._z[0],
                    next_x=candidate_x, next_z=self._z[0],
                    current_ground_y=ground_y,
                    next_ground_y=self._ground_contact_height_locked(candidate_x, self._z[0]),
                    player_y=self._y[0],
                    airborne=not self._grounded,
                )["allowed"]
                z_only = mobility_contract.ground_surface_contact(
                    current_x=self._x[0], current_z=self._z[0],
                    next_x=self._x[0], next_z=candidate_z,
                    current_ground_y=ground_y,
                    next_ground_y=self._ground_contact_height_locked(self._x[0], candidate_z),
                    player_y=self._y[0],
                    airborne=not self._grounded,
                )["allowed"]
                if x_only:
                    self._x[0] = candidate_x
                    self._vz[0] = 0.0
                elif z_only:
                    self._z[0] = candidate_z
                    self._vx[0] = 0.0
                else:
                    self._vx[0] = 0.0
                    self._vz[0] = 0.0
            landed_ground_y = self._ground_contact_height_locked(
                self._x[0], self._z[0]
            )
            if ground_y - landed_ground_y > mobility_contract.MAX_STEP_UP_M:
                # Leave a ledge as a fall instead of teleporting the root to
                # the lower sample. The next fixed steps apply gravity and
                # still allow the existing coyote-time jump window.
                self._grounded = False
                self._vy[0] = min(0.0, self._vy[0])
            if brake > 0.0:
                brake_factor = max(0.0, 1.0 - min(1.0, brake * 10.0 * dt))
                self._vx[0] *= brake_factor
                self._vz[0] *= brake_factor
        elif self._vehicle_kind != "BOAT" and self._movement_mode == "SWIM":
            water = self._water_sample_locked(self._x[0], self._z[0])
            terrain_y = self._terrain_height_locked(self._x[0], self._z[0])
            water_depth = max(0.0, water["height_m"] - terrain_y)
            if getattr(self,'_engine_world',None) is not None and water.get('body_kind')=='NONE':
                # Finish this transition tick at the current swim height. The
                # no-liquid sentinel must never become the buoyancy target.
                water={**water,'height_m':self._y[0]-.18}
            swim_motion = mobility_contract.swim_step(
                x=self._x[0], z=self._z[0], yaw=self._yaw[0],
                vx=self._vx[0], vy=self._vy[0], vz=self._vz[0],
                forward=forward, strafe=strafe, turn=turn_input,
                vertical=vertical, boost=boost, brake=brake,
                y=self._y[0], terrain_y=terrain_y,
                water_y=water["height_m"], water_depth=water_depth,
                current_x=water["current_mps"]["x"],
                current_z=water["current_mps"]["z"], dt=dt,
                submerged_volume=water.get('has_surface') is False,
            )
            self._x[0] = swim_motion["x"]
            previous_y=self._y[0];self._y[0] = swim_motion["y"]
            self._z[0] = swim_motion["z"]
            self._vx[0] = swim_motion["vx"]
            self._vy[0] = swim_motion["vy"]
            self._vz[0] = swim_motion["vz"]
            self._yaw[0] = swim_motion["yaw"]
            imported=getattr(self,'_engine_world',None)
            if imported is not None:
                if self._y[0]>previous_y:
                    ceiling=imported.ceiling(self._x[0],previous_y+.65,self._z[0])
                    if ceiling is not None and self._y[0]+.65>ceiling:self._y[0]=ceiling-.65;self._vy[0]=min(0.,self._vy[0])
                before=(self._x[0],self._z[0]);self._x[0],self._z[0]=imported.collide(self._x[0],self._y[0],self._z[0])
                if self._x[0]!=before[0]:self._vx[0]=0.
                if self._z[0]!=before[1]:self._vz[0]=0.
            seabed_clearance_y = (
                self._terrain_height_locked(self._x[0], self._z[0]) + 0.42
            )
            if self._y[0] < seabed_clearance_y:
                self._y[0] = seabed_clearance_y
                self._vy[0] = max(0.0, self._vy[0])
            self._grounded = False
            self._jump_held = False
            self._jump_count = 0
            self._double_jump_pose_remaining_s = 0.0
            self._coyote_time_remaining_s = 0.0
            self._jump_buffer_remaining_s = 0.0
            self._jump_hold_time_s = 0.0
            self._sprinting = bool(boost and abs(forward) > 0.01)
            new_depth = self._water_depth_locked(self._x[0], self._z[0])
            if new_depth <= mobility_contract.SWIM_EXIT_DEPTH_M:
                self._movement_mode = "GROUND"
                self._input["movement_mode"] = "GROUND"
                floor_y=self._ground_contact_height_locked(self._x[0],self._z[0])
                if imported is None or self._y[0]<=floor_y+.025:
                    self._y[0]=floor_y;self._vy[0]=0.;self._grounded=True
                else:self._vy[0]=min(0.,self._vy[0]);self._grounded=False
                self._append_event_locked("SHORE_EXIT", "Player reached walkable shore.")
        elif self._vehicle_kind != "BOAT":
            flight_motion = mobility_contract.flight_step(
                x=self._x[0], z=self._z[0], yaw=self._yaw[0],
                vx=self._vx[0], vy=self._vy[0], vz=self._vz[0],
                forward=forward, strafe=strafe, turn=turn_input,
                vertical=vertical, boost=boost, y=self._y[0],
                terrain_y=self._terrain_height_locked(self._x[0], self._z[0]), dt=dt,
            )
            self._x[0] = flight_motion["x"]
            self._y[0] = flight_motion["y"]
            self._z[0] = flight_motion["z"]
            self._vx[0] = flight_motion["vx"]
            self._vy[0] = flight_motion["vy"]
            self._vz[0] = flight_motion["vz"]
            self._yaw[0] = flight_motion["yaw"]
            self._grounded = False
            self._jump_held = False
            self._jump_count = 0
            self._double_jump_pose_remaining_s = 0.0
            self._coyote_time_remaining_s = 0.0
            self._jump_buffer_remaining_s = 0.0
            self._jump_hold_time_s = 0.0
            self._sprinting = False
            flight_floor_y = (
                self._terrain_height_locked(self._x[0], self._z[0])
                + mobility_contract.PLAYER_ROOT_HEIGHT_M
            )
            if self._y[0] < flight_floor_y:
                self._y[0] = flight_floor_y
                self._vy[0] = max(0.0, self._vy[0])

        if (
            self._grapple_anchor is not None
            and self._vehicle_kind == "NONE"
            and self._movement_mode == "GROUND"
        ):
            predicted_floor = self._ground_contact_height_locked(
                self._x[0] + self._vx[0] * dt,
                self._z[0] + self._vz[0] * dt,
            )
            constrained = controller.grapple_constraint(
                position=(self._x[0], self._y[0], self._z[0]),
                velocity=(self._vx[0], self._vy[0], self._vz[0]),
                anchor=self._grapple_anchor,
                rope_length=self._grapple_rope_length,
                yaw=self._yaw[0],
                forward=forward,
                strafe=strafe,
                dt=dt,
                ground_y=predicted_floor,
            )
            self._x[0] = constrained["x"]
            self._y[0] = constrained["y"]
            self._z[0] = constrained["z"]
            self._vx[0] = constrained["vx"]
            self._vy[0] = constrained["vy"]
            self._vz[0] = constrained["vz"]
            actual_floor = self._ground_contact_height_locked(self._x[0], self._z[0])
            if self._y[0] <= actual_floor + 0.025:
                self._y[0] = actual_floor
                self._grounded = True
                self._vy[0] = max(0.0, self._vy[0])
                self._jump_count = 0
                self._coyote_time_remaining_s = controller.COYOTE_TIME_S
            else:
                self._grounded = False

        if (
            self._vehicle_kind == "NONE"
            and self._movement_mode == "GROUND"
            and self._grapple_anchor is None
        ):
            if self._water_depth_locked(self._x[0], self._z[0]) > mobility_contract.MIN_SWIMMABLE_DEPTH_M:
                water = self._water_sample_locked(self._x[0], self._z[0])
                if getattr(self,'_engine_world',None) is None or self._y[0]<=water['height_m']+.3:
                    self._movement_mode = "SWIM"
                    self._input["movement_mode"] = "SWIM"
                    if water.get('has_surface') is not False:self._y[0] = max(self._y[0], water["height_m"] + 0.18)
                    self._grounded = False
                    self._append_event_locked("WATER_ENTRY", "Player entered liquid and began swimming.")

        if self._vehicle_kind == "BOAT" and boat_index is not None:
            # The rider shares the hull's sampled wave orientation as well as
            # its height. Otherwise the boat rocks under an upright avatar.
            self._pitch[0] = self._pitch[boat_index]
            self._roll[0] = self._roll[boat_index]
        elif self._vehicle_kind != "HOVERBOARD":
            self._pitch[0] = 0.0
            self._roll[0] = 0.0

        self._locomotion_distance_m += math.hypot(
            self._x[0] - previous_player_x,
            self._z[0] - previous_player_z,
        )

        speed = math.sqrt(
            self._vx[0] * self._vx[0]
            + self._vy[0] * self._vy[0]
            + self._vz[0] * self._vz[0]
        )

        boundary = max(abs(value) for value in planet_contract.MAP_BOUNDS_M.values()) + CHUNK_SIZE * 4
        if abs(self._x[0]) > boundary:
            self._x[0] = max(-boundary, min(boundary, self._x[0]))
            self._vx[0] *= -0.55
            self._burst_locked(self._x[0], 0.65, self._z[0], 12)
        if abs(self._z[0]) > boundary:
            self._z[0] = max(-boundary, min(boundary, self._z[0]))
            self._vz[0] *= -0.55
            self._burst_locked(self._x[0], 0.65, self._z[0], 12)

        if (
            self._movement_mode == "GROUND"
            and self._vehicle_kind == "NONE"
            and self._grapple_anchor is None
        ):
            # Ground movement follows the same continuous heightfield that the
            # renderer receives. There is no per-cell teleport or zone seam.
            # Enterable huts raise the floor to the deck when the player is on it.
            ground_y = self._ground_contact_height_locked(self._x[0], self._z[0])
            if self._grounded and not self._jump_held:
                self._y[0] = ground_y
                self._vy[0] = 0.0
            elif self._y[0] <= ground_y:
                self._y[0] = ground_y
                self._vy[0] = 0.0
                self._grounded = True

        # Population promotion happens before the individual/world-use pass so
        # a newly promoted resident can participate in this same fixed-step
        # lifecycle.  It removes an ambient proxy at the same time, keeping
        # the render population stable while the authoritative actor pool
        # grows only within its explicit budget.
        from backend.game_engine_adapter_triggers import tick as tick_world_triggers
        tick_world_triggers(self)
        self._tick_world_events_locked()
        self._tick_population_locked()
        self._tick_individuals_locked()
        self._tick_npcs_locked(dt)
        self._tick_survival_locked(dt)
        self._tick_combat_locked()
        self._tick_spells_locked(dt)
        self._tick_services_locked(dt)
        self._tick_social_locked()
        self._world_population.tick(self._sim_time)

        grid = (
            self._build_spatial_grid_locked()
            if self._vehicle_kind != "BOAT"
            else {}
        )
        player_cell = (
            math.floor(self._x[0] / 2.0),
            math.floor(self._z[0] / 2.0),
        )
        for cell_x in range(player_cell[0] - 1, player_cell[0] + 2):
            for cell_z in range(player_cell[1] - 1, player_cell[1] + 2):
                for other in grid.get((cell_x, cell_z), []):
                    dx = self._x[other] - self._x[0]
                    dz = self._z[other] - self._z[0]
                    distance = math.hypot(dx, dz)
                    minimum = self._radius[other] + self._radius[0]
                    if distance >= minimum:
                        continue
                    if self._kind[other] == "HOUSE":
                        continue
                    # The grid indexes XZ only; reject objects below/above the body.
                    obstacle_low=self._y[other]-abs(self._sy[other])
                    obstacle_high=self._y[other]+abs(self._sy[other])
                    if (self._y[0]-mobility_contract.PLAYER_ROOT_HEIGHT_M>obstacle_high+.2
                            or self._y[0]+1.7<obstacle_low-.2):
                        continue
                    if distance < 0.0001:
                        dx, dz, distance = 1.0, 0.0, 1.0
                    nx, nz = dx / distance, dz / distance
                    overlap = minimum - distance
                    self._x[0] -= nx * overlap
                    self._z[0] -= nz * overlap
                    normal_velocity = self._vx[0] * nx + self._vz[0] * nz
                    if normal_velocity > 0.0:
                        self._vx[0] -= normal_velocity * 1.7 * nx
                        self._vz[0] -= normal_velocity * 1.7 * nz
                    if speed > 5.0 and self._collision_cooldown <= 0.0:
                        self._collision_cooldown = 0.28
                        self._burst_locked(self._x[0], 0.9, self._z[0], 28)
                        self._append_event_locked("COLLISION", f"Player hit {self._kind[other].lower()}.")
        if self._vehicle_kind != "BOAT":
            self._tick_house_walls_locked()
        if (
            self._grapple_anchor is not None
            and self._movement_mode == "GROUND"
            and self._vehicle_kind == "NONE"
        ):
            # Entity and hut collision resolution can nudge the avatar off the
            # rope sphere. Resolve the taut line once more at the end of the
            # fixed step, with no extra swing input or acceleration.
            final_floor = self._ground_contact_height_locked(self._x[0], self._z[0])
            constrained = controller.grapple_constraint(
                position=(self._x[0], self._y[0], self._z[0]),
                velocity=(self._vx[0], self._vy[0], self._vz[0]),
                anchor=self._grapple_anchor,
                rope_length=self._grapple_rope_length,
                yaw=self._yaw[0],
                dt=0.0,
                ground_y=final_floor,
            )
            self._x[0] = constrained["x"]
            self._y[0] = constrained["y"]
            self._z[0] = constrained["z"]
            self._vx[0] = constrained["vx"]
            self._vy[0] = constrained["vy"]
            self._vz[0] = constrained["vz"]
        if (not previously_grounded and self._grounded
                and previous_vertical_speed < -.8
                and self._movement_mode == "GROUND" and self._vehicle_kind == "NONE"
                and not self._character_action_for_locked("player")
                and self._combat_state.get("actors", {}).get("player", {}).get("alive", True)):
            self._start_character_action_locked("player", "Land")
        self._tick_landmark_visits_locked()

        self._sync_ride_particles_locked()
        particle_offset = 0
        while particle_offset < len(self._active_particle_indices):
            index = self._active_particle_indices[particle_offset]
            if self._plife[index] <= 0.0:
                self._active_particle_indices.pop(particle_offset)
                self._particle_count = max(0, self._particle_count - 1)
                continue
            self._plife[index] -= dt
            if self._plife[index] <= 0.0:
                self._plife[index] = 0.0
                self._particle_count = max(0, self._particle_count - 1)
                self._active_particle_indices.pop(particle_offset)
                continue
            self._pvy[index] -= 13.0 * dt
            self._px[index] += self._pvx[index] * dt
            self._py[index] = max(self._ride_particle_floor_locked(index), self._py[index] + self._pvy[index] * dt)
            self._pz[index] += self._pvz[index] * dt
            self._pvx[index] *= 0.985
            self._pvz[index] *= 0.985
            particle_offset += 1

        if self._tick % 3 == 0:
            self._network_seq += 1

        self._tick_rigid_physics_locked(dt)
        self._tick_auto_attack_locked()
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        self._last_tick_ms = elapsed_ms
        self._max_tick_ms = max(self._max_tick_ms, elapsed_ms)

    def _run_loop(self) -> None:
        deadline = time.perf_counter()
        while not self._stop.is_set():
            with self._lock:
                running = self._running
            if not running:
                deadline = time.perf_counter() + FIXED_DT
                self._stop.wait(0.04)
                continue
            now = time.perf_counter()
            if now < deadline:
                self._stop.wait(min(deadline - now, 0.01))
                continue
            steps = 0
            while now >= deadline and steps < MAX_CATCH_UP_STEPS:
                with self._lock:
                    if not self._running:
                        break
                    self._tick_locked(FIXED_DT)
                    # Publish one complete, immutable presentation frame on the
                    # simulation lane. The Qt thread reads the last completed
                    # frame instead of waiting for terrain/pose construction.
                    frame = self.render_snapshot_locked()
                    frame['_qt_nature'] = (self._nature.groups, self._nature.revision)
                    self._published_nature = (self._nature.groups, self._nature.revision)
                    self._published_frame = frame
                deadline += FIXED_DT
                steps += 1
                now = time.perf_counter()
            if steps == MAX_CATCH_UP_STEPS and now >= deadline:
                deadline = now + FIXED_DT

    def _ensure_thread_locked(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="gg-game-engine-runtime",
            daemon=True,
        )
        self._thread.start()

    def start(self) -> dict[str, Any]:
        with self._lock:
            self._ensure_thread_locked()
            self._running = True
            self._append_event_locked("PLAY", "Fixed-step simulation running at 60 Hz.")
            return self.snapshot_locked()

    def start_render(self) -> dict[str, Any]:
        """Resume play using the compact cached render view for the player UI."""
        with self._lock:
            self._ensure_thread_locked()
            self._running = True
            self._append_event_locked("PLAY", "Fixed-step simulation running at 60 Hz.")
            if self._render_snapshot_cache is None:
                return self.snapshot_locked()
            return self._render_snapshot_from_cache_locked()

    def pause(self) -> dict[str, Any]:
        with self._lock:
            self._running = False
            self._append_event_locked("PAUSE", "Simulation paused; render state retained.")
            return self.snapshot_locked()

    def pause_render(self) -> dict[str, Any]:
        """Pause without rebuilding the large editor/inspector snapshot."""
        with self._lock:
            self._running = False
            self._input.update({
                "throttle": 0.0,
                "steer": 0.0,
                "turn": 0.0,
                "brake": 0.0,
                "boost": False,
                "forward": 0.0,
                "strafe": 0.0,
                "vertical": 0.0,
                "jump": False,
                "grapple": False,
                "ability_1": False,
                "ability_2": False,
                "ability_3": False,
            })
            self._jump_held = False
            self._grapple_held = False
            self._sprinting = False
            for ability_id in self._ability_held:
                self._ability_held[ability_id] = False
            self._append_event_locked("PAUSE", "Simulation paused; render state retained.")
            if self._render_snapshot_cache is None:
                return self.snapshot_locked()
            return self._render_snapshot_from_cache_locked()

    def character_create(self, request: Any) -> dict[str, Any]:
        with self._lock:
            response=character_creation.view(self._character_creation)
            try:
                if isinstance(request,str):request=json.loads(request)
                if not isinstance(request,dict):raise ValueError('Ogiltigt karaktärsval.')
                operation=str(request.get('op','CATALOG')).upper()
                selection=request.get('selection') or response['selection']
                if operation in {'PREVIEW','APPLY'}:
                    response['preview']=character_creation.preview(selection)
                    response['selection']=response['preview']['selection']
                    if operation=='APPLY':
                        self._character_creation=character_creation.save_selection(selection)
                        self._render_snapshot_cache=None
                        self._render_snapshot_signature=None
                        response['active']=True
                        response['applied']=True
                elif operation!='CATALOG':raise ValueError('Okänt karaktärsval.')
                else:response['preview']=character_creation.preview(selection)
            except (OSError,ValueError,KeyError,TypeError) as exc:
                response['error']=str(exc)
            return response

    def reset(self) -> dict[str, Any]:
        with self._lock:
            self._running = False
            self._recording = False
            self._replaying = False
            self._recorded_inputs = []
            self._replay_inputs = []
            self._replay_index = 0
            self._reset_world_locked()
            if getattr(self,'_engine_world',None) is not None:
                self._x[0],self._y[0],self._z[0]=self._engine_world.config['spawn'];self._engine_world.safe=None
            return self.snapshot_locked()

    def step(self) -> dict[str, Any]:
        with self._lock:
            if not self._running:
                self._running = True
                self._tick_locked(FIXED_DT)
                self._running = False
            return self.snapshot_locked()

    def explore_region(self, region_id: str) -> dict[str, Any]:
        """Explicit local exploration jump to a known atlas destination."""
        with self._lock:
            if self._instance_private_locked():return {'schema':SCHEMA,'error':'INSTANCE_EXIT_REQUIRED'}
            if self._player_defeated_locked():return {"schema":SCHEMA,"error":"PLAYER_DEFEATED"}
            if self._services.get('taxi_flight'):return {"schema":SCHEMA,"error":"TAXI_IN_PROGRESS"}
            wanted = str(region_id or "").upper()
            regions = planet_contract.map_contract()["landmasses"]
            region = next((r for r in regions if r["id"] == wanted), None)
            if region is None:
                return {"schema": SCHEMA, "error": "EXPLORATION_REGION_UNKNOWN"}
            center = region["center_m"]
            x, z = float(center["x"]), float(center["z"])
            town=next((p for p in world_places_contract.catalog()['places'] if p['region_id']==wanted and p['kind']=='TOWN'),None)
            if town:x,z=town['x'],town['z']
            self._vehicle_kind = "NONE"
            self._boat_entity_index = None
            self._combat_target_id = ""
            self._x[0], self._z[0] = x, z
            self._y[0] = self._terrain_height_locked(x, z) + 8.0
            self._vx[0] = self._vy[0] = self._vz[0] = 0.0
            self._input = self._default_input()
            self._input["movement_mode"] = self._movement_mode = "FLY"
            self._grounded = False
            self._jump_held = False
            self._jump_buffer_remaining_s = self._jump_hold_time_s = 0.0
            self._coyote_time_remaining_s = 0.0
            self._append_event_locked("EXPLORE_REGION", f"Exploring {region['name']}.")
            snapshot = self.snapshot_locked()
            snapshot["exploration_result"] = {"region": region["id"], "name": region["name"]}
            return snapshot

    def set_movement_mode(self, mode: str) -> dict[str, Any]:
        normalized = world.normalize_movement_mode(mode, "")
        if not normalized:
            return {
                "schema": SCHEMA,
                "error": "GAME_ENGINE_MOVEMENT_MODE_INVALID",
                "allowed": list(MOVEMENT_MODES),
            }
        with self._lock:
            if self._player_defeated_locked() and normalized!='GROUND':return {"schema":SCHEMA,"error":"PLAYER_DEFEATED"}
            if self._services.get('taxi_flight'):return {"schema":SCHEMA,"error":"TAXI_IN_PROGRESS"}
            if self._vehicle_kind != "NONE" and normalized != "GROUND":
                return {
                    "schema": SCHEMA,
                    "error": "EXIT_VEHICLE_BEFORE_CHANGING_MOVEMENT_MODE",
                    "vehicle": self._vehicle_kind,
                    "requested_mode": normalized,
                }
            if normalized == self._movement_mode:
                return self.snapshot_locked()
            previous = self._movement_mode
            self._movement_mode = normalized
            self._input["movement_mode"] = normalized
            if normalized == "GROUND":
                self._vy[0] = 0.0
                self._y[0] = self._ground_contact_height_locked(
                    self._x[0], self._z[0]
                )
                self._grounded = True
                self._jump_held = False
                self._coyote_time_remaining_s = 0.0
                self._jump_buffer_remaining_s = 0.0
                self._jump_hold_time_s = 0.0
            elif previous == "GROUND":
                self._y[0] = max(1.2, self._y[0] + 1.0)
            self._append_event_locked(
                "MOVEMENT_MODE",
                f"Movement mode changed: {previous} -> {normalized}.",
            )
            return self.snapshot_locked()

    def _mobility_action_locked(self, action: str) -> dict[str, Any]:
        if self._player_defeated_locked():return {"ok":False,"error":"PLAYER_DEFEATED"}
        if self._services.get('taxi_flight'):return {"ok":False,"error":"TAXI_IN_PROGRESS"}
        wanted = str(action or "").strip().upper()
        player_x = self._x[0]
        player_z = self._z[0]
        depth = self._water_depth_locked(player_x, player_z)

        if wanted == "TOGGLE_FLIGHT":
            if self._vehicle_kind != "NONE":
                return {
                    "ok": False,
                    "error": "EXIT_VEHICLE_BEFORE_FLIGHT",
                    "vehicle": self._vehicle_kind,
                }
            if self._movement_mode == "FLY":
                self._movement_mode = "GROUND"
                self._input["movement_mode"] = "GROUND"
                floor_y = self._ground_contact_height_locked(player_x, player_z)
                if self._y[0] <= floor_y + 0.03:
                    self._y[0] = floor_y
                    self._vy[0] = 0.0
                    self._grounded = True
                    self._coyote_time_remaining_s = controller.COYOTE_TIME_S
                else:
                    # Landing from the flight test mode is an actual fall;
                    # keep the current height and let the fixed-step gravity
                    # bring the player down onto the same terrain collider.
                    self._vy[0] = min(0.0, self._vy[0])
                    self._grounded = False
                    self._coyote_time_remaining_s = 0.0
                self._append_event_locked("FLIGHT_LAND", "Flight ended; player is descending to terrain.")
            else:
                self._movement_mode = "FLY"
                self._input["movement_mode"] = "FLY"
                floor_y = self._ground_contact_height_locked(player_x, player_z)
                water_surface_y = self._water_sample_locked(
                    player_x, player_z
                )["height_m"] + 0.7
                self._y[0] = max(self._y[0], floor_y + 0.9, water_surface_y)
                self._vy[0] = max(0.0, self._vy[0])
                self._grounded = False
                self._jump_held = False
                self._coyote_time_remaining_s = 0.0
                self._jump_buffer_remaining_s = 0.0
                self._jump_hold_time_s = 0.0
                self._append_event_locked("FLIGHT_TAKEOFF", "Free-flight test mode engaged.")
            self._sprinting = False
            return {
                "ok": True,
                "action": wanted,
                "vehicle": self._vehicle_kind,
                "movement_mode": self._movement_mode,
                "grounded": self._grounded,
            }

        if wanted == "TOGGLE_HOVERBOARD":
            if self._vehicle_kind == "BOAT":
                return {"ok": False, "error": "EXIT_BOAT_FIRST"}
            if self._vehicle_kind == "HOVERBOARD":
                was_airborne = not self._grounded
                vertical_velocity = self._vy[0]
                self._vehicle_kind = "NONE"
                if depth > mobility_contract.SWIM_EXIT_DEPTH_M:
                    self._movement_mode = "SWIM"
                    self._input["movement_mode"] = "SWIM"
                    water=self._water_sample_locked(player_x,player_z)
                    if water.get('has_surface') is not False:self._y[0]=max(self._y[0],water['height_m']+.18)
                    self._vy[0] = 0.0
                    self._grounded = False
                else:
                    self._movement_mode = "GROUND"
                    self._input["movement_mode"] = "GROUND"
                    floor_y = self._ground_contact_height_locked(player_x, player_z)
                    if was_airborne and self._y[0] > floor_y + 0.03:
                        self._vy[0] = min(0.0, vertical_velocity)
                        self._grounded = False
                    else:
                        self._y[0] = floor_y
                        self._vy[0] = 0.0
                        self._grounded = True
                self._append_event_locked("HOVERBOARD_EXIT", "Player stepped off the hoverboard.")
                return {"ok": True, "action": wanted, "vehicle": "NONE"}
            if self._movement_mode == "FLY":
                return {"ok": False, "error": "LAND_BEFORE_HOVERBOARD"}
            if (
                self._movement_mode == "GROUND"
                and not self._grounded
                and self._y[0]
                > self._ground_contact_height_locked(player_x, player_z) + 0.15
            ):
                return {"ok": False, "error": "LAND_BEFORE_HOVERBOARD"}
            self._vehicle_kind = "HOVERBOARD"
            self._movement_mode = "GROUND"
            self._y[0] = self._ground_contact_height_locked(
                player_x, player_z, vehicle_kind="HOVERBOARD"
            )
            self._vy[0] = 0.0
            self._grounded = True
            self._jump_held = False
            self._coyote_time_remaining_s = controller.COYOTE_TIME_S
            self._jump_buffer_remaining_s = 0.0
            self._jump_hold_time_s = 0.0
            self._append_event_locked("HOVERBOARD_ENTER", "Hoverboard ready; jump height follows button hold.")
            return {"ok": True, "action": wanted, "vehicle": self._vehicle_kind}

        if wanted == "MOUNT_BOAT":
            boat_index = self._ride_boat_index_locked()
            if self._vehicle_kind == "BOAT":
                if boat_index is not None and self._alive[boat_index]:
                    boat_x = self._x[boat_index]
                    boat_z = self._z[boat_index]
                    # Step toward the island, clear of the longer hull.
                    toward_land_x = -boat_x
                    toward_land_z = -boat_z
                    length = max(0.001, math.hypot(toward_land_x, toward_land_z))
                    self._x[0] = boat_x + toward_land_x / length * 3.2
                    self._z[0] = boat_z + toward_land_z / length * 3.2
                    self._vx[0] = self._vx[boat_index]
                    self._vz[0] = self._vz[boat_index]
                    depth = self._water_depth_locked(self._x[0], self._z[0])
                    if depth > mobility_contract.SWIM_EXIT_DEPTH_M:
                        self._movement_mode = "SWIM"
                        self._input["movement_mode"] = "SWIM"
                        water=self._water_sample_locked(self._x[0],self._z[0])
                        if water.get('has_surface') is not False:self._y[0]=water['height_m']+.18
                        self._grounded = False
                    else:
                        self._movement_mode = "GROUND"
                        self._input["movement_mode"] = "GROUND"
                        self._y[0] = self._ground_contact_height_locked(
                            self._x[0], self._z[0]
                        )
                        self._grounded = True
                    self._static[boat_index] = True
                    bisect.insort(self._static_entity_indices, boat_index)
                self._vehicle_kind = "NONE"
                self._vy[0] = 0.0
                self._append_event_locked("BOAT_EXIT", "Player left the skiff at the cove.")
                return {"ok": True, "action": wanted, "vehicle": "NONE"}
            if self._vehicle_kind == "HOVERBOARD":
                return {"ok": False, "error": "EXIT_HOVERBOARD_FIRST"}
            if boat_index is None or not self._alive[boat_index]:
                return {"ok": False, "error": "SKIFF_UNAVAILABLE"}
            boat_x = self._x[boat_index]
            boat_z = self._z[boat_index]
            distance = math.hypot(player_x - boat_x, player_z - boat_z)
            if distance > mobility_contract.SKIFF_BOARD_RADIUS_M:
                return {"ok": False, "error": "TOO_FAR_FROM_SKIFF", "distance_m": round(distance, 2)}
            seat_height = (
                self._y[boat_index]
                + mobility_contract.skiff_seat_offset(self._sy[boat_index])
            )
            if abs(self._y[0] - seat_height) > mobility_contract.SKIFF_BOARD_HEIGHT_M:
                return {"ok": False, "error": "SKEWED_HEIGHT_FROM_SKIFF"}
            # Depth is the seabed under calm sea, not the passing trough,
            # or a swell would lock the player out of the hull.
            seabed = max(
                0.0,
                terrain_contract.SEA_LEVEL
                - self._terrain_height_locked(boat_x, boat_z),
            )
            if seabed < mobility_contract.SKIFF_BOARD_DEPTH_M:
                return {"ok": False, "error": "BOAT_IN_SHALLOWS"}
            if self._static[boat_index]:
                self._static[boat_index] = False
                if boat_index in self._static_entity_indices:
                    self._static_entity_indices.remove(boat_index)
            self._vehicle_kind = "BOAT"
            self._movement_mode = "GROUND"
            self._x[0] = boat_x
            self._z[0] = boat_z
            self._y[0] = (
                self._y[boat_index]
                + mobility_contract.skiff_seat_offset(self._sy[boat_index])
            )
            self._yaw[0] = self._yaw[boat_index]
            self._vx[0] = self._vx[boat_index]
            self._vy[0] = 0.0
            self._vz[0] = self._vz[boat_index]
            self._grounded = True
            self._jump_held = False
            self._append_event_locked("BOAT_ENTER", "Player boarded the cove skiff.")
            return {"ok": True, "action": wanted, "vehicle": self._vehicle_kind}

        return {"ok": False, "error": "MOBILITY_ACTION_INVALID", "action": wanted}

    def mobility_action(self, action: str) -> dict[str, Any]:
        with self._lock:
            result = self._mobility_action_locked(action)
            snapshot = self.snapshot_locked()
            snapshot["mobility_action"] = result
            return snapshot

    def mobility_water_clock(self) -> dict[str, Any]:
        with self._lock:
            return {
                "time_s": self._sim_time,
                "sea_level_m": terrain_contract.SEA_LEVEL,
            }

    def _set_input_locked(self, raw: str) -> dict[str, Any] | None:
        """Apply one input packet while the runtime lock is held.

        Input is authoritative simulation data.  The caller chooses whether
        it needs the full inspector snapshot (commands/tests) or only the
        bounded render stream (the 60 Hz movement path).
        """
        try:
            payload = json.loads(str(raw or "{}"))
        except (TypeError, ValueError):
            return {"schema": SCHEMA, "error": "GAME_ENGINE_INPUT_INVALID"}
        if not isinstance(payload, dict):
            return {"schema": SCHEMA, "error": "GAME_ENGINE_INPUT_INVALID"}
        requested_mode = payload.get("movement_mode", self._movement_mode)
        normalized_mode = world.normalize_movement_mode(
            requested_mode, self._movement_mode
        )
        if self._opening_cinematic:normalized_mode='GROUND'
        elif self._player_defeated_locked():normalized_mode='GROUND'
        elif self._services.get('taxi_flight'):normalized_mode='FLY'
        self._movement_mode = normalized_mode
        mouse_look = bool(payload.get("mouse_look")) and not self._opening_cinematic
        facing_yaw = _clamp(payload.get("facing_yaw"), -180.0, 180.0,
                            math.degrees(self._yaw[0]))
        if mouse_look:
            self._yaw[0] = math.radians(facing_yaw)
        if not self._opening_cinematic:
            self._camera_yaw = _clamp(payload.get("camera_yaw"), -360.0, 360.0)
            self._camera_pitch = _clamp(payload.get("camera_pitch"), -89.0, 89.0, -8.0)
            self._camera_distance = _clamp(
                payload.get("camera_distance"),
                0.0,
                160.0,
                world.DEFAULT_CAMERA_DISTANCE_M,
            )
        if payload.get('cancel_legacy_input'):
            self._legacy_held.clear();self._legacy_autorun=False;self._legacy_jump=False
        self._input = {
            "throttle": _clamp(payload.get("throttle"), -1.0, 1.0),
            "steer": _clamp(
                payload.get("turn", payload.get("steer")), -1.0, 1.0
            ),
            "turn": _clamp(
                payload.get("turn", payload.get("steer")), -1.0, 1.0
            ),
            "brake": _clamp(payload.get("brake"), 0.0, 1.0),
            "boost": bool(payload.get("boost")),
            "forward": _clamp(
                payload.get("forward", payload.get("throttle")), -1.0, 1.0
            ),
            "strafe": _clamp(payload.get("strafe"), -1.0, 1.0),
            "vertical": _clamp(payload.get("vertical"), -1.0, 1.0),
            "jump": bool(payload.get("jump")),
            "grapple": bool(payload.get("grapple")),
            "movement_mode": normalized_mode,
            "mouse_look": mouse_look,
            "facing_yaw": facing_yaw,
            "camera_yaw": self._camera_yaw,
            "camera_pitch": self._camera_pitch,
            "camera_distance": self._camera_distance,
            "ability_1": bool(payload.get("ability_1")),
            "ability_2": bool(payload.get("ability_2")),
            "ability_3": bool(payload.get("ability_3")),
        }

        return None

    def set_input(self, raw: str) -> dict[str, Any]:
        with self._lock:
            error = self._set_input_locked(raw)
            if error is not None:
                return error
            return self.snapshot_locked()

    def set_input_render(self, raw: str) -> dict[str, Any]:
        """Apply input and return the compact render view without UI rebuild."""
        with self._lock:
            error = self._set_input_locked(raw)
            if error is not None:
                return error
            return self.render_snapshot_locked()

    def _finish_dos_command_locked(
        self,
        parsed: dict[str, Any],
        *,
        ok: bool,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        row = dos_contract.record(
            parsed,
            ok=ok,
            message=message,
            details=details,
        )
        self._last_dos_command = row
        self._dos_history = (self._dos_history + [row])[-dos_contract.MAX_HISTORY:]
        snapshot = self.snapshot_locked()
        snapshot["dos_command"] = copy.deepcopy(row)
        snapshot["dos"] = dos_contract.history_view(
            self._dos_history,
            self._last_dos_command,
        )
        return snapshot

    def _dos_transient_input_locked(
        self,
        updates: dict[str, Any],
        steps: int = 1,
    ) -> dict[str, Any]:
        """Apply a finite command input through the normal fixed-step path."""
        safe_steps = max(1, min(dos_contract.MAX_MOVE_STEPS, int(steps)))
        previous_input = dict(self._input)
        previous_jump_held = self._jump_held
        previous_running = self._running
        before = (self._x[0], self._y[0], self._z[0])
        try:
            # A DOS movement command is a finite input impulse.  It may be
            # issued while PLAY is paused, but it still travels through the
            # normal fixed-step gate and then returns to the prior run state.
            self._running = True
            for _ in range(safe_steps):
                current = dict(previous_input)
                current.update(updates)
                current.update(
                    {
                        "movement_mode": self._movement_mode,
                        "camera_yaw": self._camera_yaw,
                        "camera_pitch": self._camera_pitch,
                        "camera_distance": self._camera_distance,
                    }
                )
                self._input = current
                self._tick_locked(FIXED_DT)
        finally:
            self._running = previous_running
            self._input = previous_input
            self._jump_held = previous_jump_held
        after = (self._x[0], self._y[0], self._z[0])
        displacement = math.sqrt(
            (after[0] - before[0]) ** 2
            + (after[1] - before[1]) ** 2
            + (after[2] - before[2]) ** 2
        )
        return {
            "steps": safe_steps,
            "from": {
                "x": _round(before[0]),
                "y": _round(before[1]),
                "z": _round(before[2]),
            },
            "to": {
                "x": _round(after[0]),
                "y": _round(after[1]),
                "z": _round(after[2]),
            },
            "displacement_m": _round(displacement, 4),
        }

    def dos_command(self, raw: str) -> dict[str, Any]:
        """Execute one validated DOS command against the canonical runtime."""
        parsed = dos_contract.parse(raw)
        with self._lock:
            if not parsed.get("ok"):
                return self._finish_dos_command_locked(
                    parsed,
                    ok=False,
                    message=f"ERROR {parsed.get('error', 'DOS_COMMAND_INVALID')}",
                    details={"usage": parsed.get("usage", "")},
                )

            command = str(parsed.get("command", "")).upper()
            args = list(parsed.get("args", []))
            if command == "HELP":
                return self._finish_dos_command_locked(
                    parsed,
                    ok=True,
                    message="DOS command grammar ready.",
                    details={"lines": dos_contract.help_lines()},
                )
            if command in {"STATUS", "LOOK"}:
                return self._finish_dos_command_locked(
                    parsed,
                    ok=True,
                    message="Authoritative snapshot returned.",
                )
            if command == "MOVE":
                direction = str(args[0]).upper()
                steps = max(1, int(args[1]))
                updates = {
                    "forward": 1.0 if direction == "FORWARD" else 0.0,
                    "throttle": 1.0 if direction == "FORWARD" else 0.0,
                    "strafe": (
                        -1.0
                        if direction == "LEFT"
                        else (1.0 if direction == "RIGHT" else 0.0)
                    ),
                    "turn": 0.0,
                    "steer": 0.0,
                    "jump": False,
                    "boost": False,
                    "ability_1": False,
                    "ability_2": False,
                    "ability_3": False,
                }
                details = self._dos_transient_input_locked(updates, steps)
                self._append_event_locked(
                    "DOS_MOVE",
                    f"DOS moved {direction.lower()} for {details['steps']} fixed steps.",
                    actor_id="player",
                    subject_id=direction,
                    payload=details,
                )
                return self._finish_dos_command_locked(
                    parsed,
                    ok=True,
                    message=(
                        f"Moved {direction.lower()} {details['steps']} step(s); "
                        f"{details['displacement_m']:.4f} m."
                    ),
                    details=details,
                )
            if command == "TURN":
                direction = str(args[0]).upper()
                steps = max(1, int(args[1]))
                details = self._dos_transient_input_locked(
                    {
                        "forward": 0.0,
                        "throttle": 0.0,
                        "strafe": 0.0,
                        "turn": -1.0 if direction == "LEFT" else 1.0,
                        "steer": -1.0 if direction == "LEFT" else 1.0,
                        "jump": False,
                        "boost": False,
                        "ability_1": False,
                        "ability_2": False,
                        "ability_3": False,
                    },
                    steps,
                )
                self._append_event_locked(
                    "DOS_TURN",
                    f"DOS turned {direction.lower()} for {details['steps']} fixed steps.",
                    actor_id="player",
                    subject_id=direction,
                    payload=details,
                )
                return self._finish_dos_command_locked(
                    parsed,
                    ok=True,
                    message=f"Turned {direction.lower()} {details['steps']} step(s).",
                    details=details,
                )
            if command == "JUMP":
                details = self._dos_transient_input_locked(
                    {
                        "forward": 0.0,
                        "throttle": 0.0,
                        "strafe": 0.0,
                        "turn": 0.0,
                        "steer": 0.0,
                        "jump": True,
                        "boost": False,
                        "ability_1": False,
                        "ability_2": False,
                        "ability_3": False,
                    }
                )
                return self._finish_dos_command_locked(
                    parsed,
                    ok=True,
                    message="Jump input committed for one fixed step.",
                    details=details,
                )
            if command == "MODE":
                result = self.set_movement_mode(str(args[0]))
            elif command == "PLAY":
                result = self.start()
            elif command == "PAUSE":
                result = self.pause()
            elif command == "STEP":
                result = self.step()
            elif command == "INTERACT":
                result = self.interact_item()
            elif command == "PICKUP":
                result = self.pickup_item(str(args[0]) if args else "")
            elif command == "OPEN":
                result = self.open_container(str(args[0]) if args else "")
            elif command == "LOOT":
                result = self.loot_container(str(args[0]) if args else "")
            elif command == "EQUIP":
                result = self.equip_item(str(args[0]) if args else "")
            elif command == "DROP":
                result = self.drop_item(str(args[0]) if args else "")
            elif command == "NPC":
                result = self.npc_interact()
            elif command == "TALK":
                result = self.talk_npc(
                    str(args[0]) if args else "",
                    str(args[1]) if len(args) > 1 else "",
                )
            elif command == "PACK":
                result = self.activate_content_pack(
                    str(args[0]) if args else "pack.tidefall-frontier"
                )
            elif command == "EVENTS":
                result = self.snapshot_locked()
            elif command == "ATTACK":
                result = self.attack(str(args[0]) if args else "")
            elif command == "QUESTS":
                result = self.snapshot_locked()
            elif command == "ACCEPT":
                result = self.accept_quest(str(args[0]) if args else "quest.shoreline-first")
            elif command == "CLAIM":
                result = self.claim_quest(str(args[0]) if args else "")
            elif command == "TRADE":
                result = self.trade_items(
                    str(args[0]) if args else "",
                    str(args[1]) if len(args) > 1 else "",
                    str(args[2]) if len(args) > 2 else "",
                )
            elif command == "BUY":
                result = self.vendor_buy(
                    str(args[0]) if args else "",
                    str(args[1]) if len(args) > 1 else "",
                )
            elif command == "SELL":
                result = self.vendor_sell(
                    str(args[0]) if args else "",
                    str(args[1]) if len(args) > 1 else "",
                )
            elif command == "CRAFT":
                result = self.craft_recipe(
                    str(args[0]) if args else "recipe.field_ration"
                )
            elif command == "GEARCRAFT":
                result = self.craft_gear(
                    str(args[0]) if args else "recipe.fiber_rope",
                    str(args[1]) if len(args) > 1 else "",
                )
            elif command == "SAVE":
                result = self.save_state()
            elif command == "LOAD":
                result = self.load_state()
            elif command == "DOS":
                result = self.set_presentation_mode(render_contract.DOS_2D)
            elif command in {"3D", "RETRY"}:
                result = self.set_presentation_mode(render_contract.RICH_3D)
            elif command == "BURST":
                result = self.burst()
            else:
                return self._finish_dos_command_locked(
                    parsed,
                    ok=False,
                    message="ERROR DOS_COMMAND_NOT_IMPLEMENTED",
                )
            error = result.get("error") if isinstance(result, dict) else None
            if error:
                snapshot = self._finish_dos_command_locked(
                    parsed,
                    ok=False,
                    message=f"ERROR {error}",
                    details={"error": str(error)},
                )
                if isinstance(result, dict):
                    for result_key in ("trade_result", "economy_result"):
                        if result_key in result:
                            snapshot[result_key] = copy.deepcopy(result[result_key])
                return snapshot
            snapshot = self._finish_dos_command_locked(
                parsed,
                ok=True,
                message=f"{command} committed.",
            )
            if isinstance(result, dict):
                for result_key in ("trade_result", "economy_result"):
                    if result_key in result:
                        snapshot[result_key] = copy.deepcopy(result[result_key])
            return snapshot

    def set_keybinding(self, action: str, key: str) -> dict[str, Any]:
        """Update one primary key without touching simulation state."""
        with self._lock:
            bindings, result = input_contract.set_binding(
                self._keybindings,
                action,
                key,
            )
            self._keybindings = bindings
            if result.get("ok"):
                self._append_event_locked(
                    "KEYBINDING",
                    f"{result['action']} bound to {result['key']}.",
                )
            snapshot = self.snapshot_locked()
            snapshot["keybinding_result"] = result
            return snapshot

    def reset_keybindings(self) -> dict[str, Any]:
        """Restore the WoW-style defaults while retaining the current world."""
        with self._lock:
            self._keybindings = input_contract.new_bindings()
            self._append_event_locked(
                "KEYBINDING_RESET",
                "WoW-style movement and ability bindings restored.",
            )
            return self.snapshot_locked()

    def set_addon(self, addon_id: str, enabled: bool) -> dict[str, Any]:
        """Toggle one built-in data-driven addon view."""
        with self._lock:
            addons, result = addons_contract.set_enabled(
                self._addons,
                addon_id,
                enabled,
            )
            self._addons = addons
            if result.get("ok"):
                self._append_event_locked(
                    "ADDON",
                    f"{result['addon_id']} {'enabled' if result['enabled'] else 'disabled'}.",
                )
            snapshot = self.snapshot_locked()
            snapshot["addon_result"] = result
            return snapshot

    def _target_rows_locked(self, *, require_sight=False, only_id="") -> list[dict[str, Any]]:
        rows = []
        actors = self._combat_state.get("actors", {})
        for index in self._npc_indices[:npc_contract.MAX_NPCS]:
            identity = str(self._npc_ids[index] or "")
            if only_id and identity != only_id:
                continue
            actor = actors.get(identity, {})
            if not identity or not self._alive[index] or not actor.get("alive", True):
                continue
            distance = math.sqrt((self._x[index]-self._x[0])**2
                                 + (self._y[index]-self._y[0])**2
                                 + (self._z[index]-self._z[0])**2)
            if distance > 64 or (require_sight and not self._npc_line_of_sight_locked(index)):
                continue
            person = self._individual_state.get("individuals", {}).get(identity, {})
            rows.append({"id": identity, "entity_id": f"e-{index:04d}","guid":index+1,
                         "can_attack": identity not in self._services['group']['members'] or self._duel_opponent_locked(identity),
                         "friend": identity in self._services['group']['members'],
                         "name": person.get("name") or str(self._npc_archetype[index]).replace("_", " ").title(),
                         "distance_m": round(distance, 3), "x": self._x[index],
                         "y": self._y[index], "z": self._z[index],
                         "health": actor.get("health", 0), "max_health": actor.get("max_health", 1)})
        return sorted(rows, key=lambda row: (row["distance_m"], row["id"]))

    def _target_view_locked(self) -> dict[str, Any]:
        if self._combat_target_id=='player':
            actor=self._combat_state.get('actors',{}).get('player',{})
            return {'schema':'gg.game-engine.targeting.v1','selected':{'id':'player','entity_id':'e-0000','guid':1,
                'name':getattr(self,'_local_character_name','Gold Goblin'),'health':actor.get('health',100),'max_health':actor.get('max_health',100),
                'is_player':True,'can_attack':False,'distance_m':0},'range_m':64,'selection_does_damage':False}
        if self._combat_target_id.startswith("nature:") or self._combat_target_id in self._item_instances:
            selected=self._selected_interaction_locked()
            if not selected:self._combat_target_id="";self._actions.auto_attack=False
            return {"schema":"gg.game-engine.targeting.v1","selected":selected,"range_m":64,"selection_does_damage":False}
        rows = self._target_rows_locked(only_id=self._combat_target_id) if self._combat_target_id else ()
        selected = next((row for row in rows
                         if row["id"] == self._combat_target_id), None)
        if selected is None:
            self._combat_target_id = ""
        return {"schema": "gg.game-engine.targeting.v1", "selected": selected or {},
                "range_m": 64, "selection_does_damage": False,
                "attack_validation": "EXISTING_AUTHORITATIVE_RANGE_LOS_COOLDOWN"}

    def cycle_target(self, reverse: bool = False) -> dict[str, Any]:
        with self._lock:
            self._ensure_combat_actors_locked()
            rows = self._target_rows_locked(require_sight=True)
            ids = [row["id"] for row in rows]
            if not ids:
                self._combat_target_id = ""
            elif self._combat_target_id in ids:
                index = ids.index(self._combat_target_id)
                self._combat_target_id = ids[(index + (-1 if reverse else 1)) % len(ids)]
            else:
                self._combat_target_id = ids[-1 if reverse else 0]
            return self.snapshot_locked()

    def clear_target(self) -> dict[str, Any]:
        with self._lock:
            self._combat_target_id = ""
            return self.snapshot_locked()

    def _firearm_rows_locked(self):
        return [row for row in self._player_equipped_instances_locked()
                if row.get('definition_id')=='item.weapon_pistol'
                and row.get('equipped_slot') in ('MAIN_HAND','OFF_HAND')]

    def _firearms_view_locked(self):
        hands=[]
        for row in self._firearm_rows_locked():
            spec,mag=firearms_contract.settle(row,self._sim_time)
            hands.append(dict(instance_id=row['instance_id'],slot=row['equipped_slot'],
                profile=spec,magazine=dict(mag),reserve=int(self._inventory.get(spec['ammo_id'],0))))
        shots=[shot for shot in getattr(self,'_firearm_shots',[]) if self._sim_time-shot['time_s']<2]
        self._firearm_shots=shots[-24:]
        return dict(hands=hands,shots=copy.deepcopy(self._firearm_shots))

    def _reload_gun_locked(self,row):
        spec,mag=firearms_contract.settle(row,self._sim_time)
        if mag['pending']:return dict(ok=False,status='RELOADING',reload_until=mag['reload_until'])
        need=spec['capacity']-mag['rounds']
        if need<=0:return dict(ok=False,status='MAGAZINE_FULL')
        stacks=sorted((r for r in self._item_instances.values()
            if r.get('owner_id')=='player' and r.get('location')=='INVENTORY'
            and r.get('definition_id')==spec['ammo_id']),key=lambda r:r['instance_id'])
        available=min(int(self._inventory.get(spec['ammo_id'],0)),sum(int(r.get('quantity',1)) for r in stacks))
        amount=min(need,available)
        if amount<=0:return dict(ok=False,status='NO_AMMO',ammo_id=spec['ammo_id'],ammo_name=spec['ammo_name'])
        remaining=amount
        for stack in stacks:
            used=min(remaining,int(stack.get('quantity',1)))
            if used and not self._consume_inventory_item_locked(stack,used):raise RuntimeError('AMMO_TRANSFER_INVARIANT')
            remaining-=used
            if not remaining:break
        mag['pending']=amount;mag['reload_until']=self._sim_time+spec['reload_s']
        self._start_character_action_locked("player", "Reload")
        return dict(ok=True,status='RELOADING',rounds_transferred=amount,reload_until=mag['reload_until'],
            slot=row['equipped_slot'],ammo_name=spec['ammo_name'])

    def reload_firearms(self):
        with self._lock:
            rows=self._firearm_rows_locked()
            results=[self._reload_gun_locked(row) for row in rows]
            snapshot=self.snapshot_locked()
            snapshot['firearm_result']=dict(action='RELOAD',hands=results)
            if not rows:snapshot['error']='FIREARM_REQUIRED'
            elif not any(row.get('ok') or row.get('status')=='RELOADING' for row in results):
                snapshot['error']='FIREARM_'+results[0]['status']
            return snapshot

    def _firearm_attack_locked(self,target_id,automatic_only=False):
        def finish(result):
            self._last_combat=copy.deepcopy(result)
            # Automatic fire uses the same bounded stream as movement. A shot
            # must not rebuild terrain/catalogues and the whole inventory UI.
            snapshot=self.render_snapshot_locked();snapshot['combat_result']=copy.deepcopy(result)
            if not result.get('ok'):snapshot['error']='FIREARM_'+result.get('status','FAILED')
            return snapshot
        self._ensure_combat_actors_locked()
        player_profile=self._player_combat_profile_locked()
        actor=combat_contract.ensure_actor(self._combat_state,'player',player_profile)
        if not actor.get('alive'):return finish(dict(ok=False,status='PLAYER_DEFEATED'))
        guns=[]
        for row in self._firearm_rows_locked():
            spec,mag=firearms_contract.settle(row,self._sim_time)
            if automatic_only and not spec['automatic']:
                continue
            ready=not mag['pending'] and mag['next_fire']<=self._sim_time+1e-8
            loaded=mag['rounds']>=spec['rounds_per_shot']
            can_reload=int(self._inventory.get(spec['ammo_id'],0))>0
            guns.append((not (ready and loaded),not ready,not can_reload,
                row['equipped_slot']==getattr(self,'_firearm_last_hand',''),row,spec,mag))
        if not guns:return finish(dict(ok=False,status='AUTOMATIC_REQUIRED'))
        _,_,_,_,row,spec,mag=min(guns,key=lambda r:r[:4])
        if mag['pending']:return finish(dict(ok=False,status='RELOADING',reload_until=mag['reload_until']))
        if mag['next_fire']>self._sim_time+1e-8:
            return finish(dict(ok=False,status='COOLDOWN',cooldown_remaining_s=mag['next_fire']-self._sim_time))
        if mag['rounds']<spec['rounds_per_shot']:
            reload_result=self._reload_gun_locked(row)
            return finish(dict(reload_result,ok=False))
        wanted=str(target_id or self._combat_target_id or '')
        candidates=[]
        for index in self._npc_indices[:npc_contract.MAX_NPCS]:
            key=self._npc_ids[index]
            if key in self._services['group']['members'] and not self._duel_opponent_locked(key):continue
            if not self._alive[index] or not key or (wanted and key!=wanted):continue
            if not self._combat_state.get('actors',{}).get(key,{}).get('alive',True):continue
            dx=self._x[index]-self._x[0];dz=self._z[index]-self._z[0];distance=math.hypot(dx,dz)
            if not wanted:
                facing=abs((math.atan2(dx,dz)-self._yaw[0]+math.pi)%math.tau-math.pi)
                if facing>math.radians(6) or distance>spec['range_m']:continue
            candidates.append((distance,str(key),index))
        candidates.sort()
        index=None;resolved_id=''
        if candidates:
            distance,resolved_id,index=candidates[0]
            if distance>spec['range_m']:return finish(dict(ok=False,status='TARGET_OUT_OF_RANGE',range_m=spec['range_m']))
            if not self._npc_line_of_sight_locked(index):return finish(dict(ok=False,status='LINE_OF_SIGHT_BLOCKED'))
            target=[self._x[index],self._y[index]+.25,self._z[index]]
        elif wanted:return finish(dict(ok=False,status='TARGET_REQUIRED'))
        else:
            distance=spec['range_m']
            target=[self._x[0]+math.sin(self._yaw[0])*distance,self._y[0]+.15,self._z[0]+math.cos(self._yaw[0])*distance]
        side=.38 if row['equipped_slot']=='MAIN_HAND' else -.38
        yaw=self._yaw[0]
        start=[self._x[0]+math.cos(yaw)*side+math.sin(yaw)*.30,self._y[0]+.13,
               self._z[0]-math.sin(yaw)*side+math.cos(yaw)*.30]
        seed=self._tick*17+mag['shots']*31+spec['variant']
        offsets=firearms_contract.projectile_offsets(spec,distance,seed)
        hits=sum(math.hypot(x,y)<=.50 for x,y in offsets) if index is not None else 0
        cooldown=(1/spec['rounds_per_s'])*(1+combat_contract.status_strength(actor,'attack_slow',self._sim_time))
        if index is not None:
            person=self._individual_state.get('individuals',{}).get(resolved_id)
            defender_profile=dict(self._npc_combat_profile_locked(resolved_id,person))
            defender_profile['armor']*=1-spec['armor_penetration']
            player_profile=dict(player_profile,damage=spec['damage_per_projectile']*hits+player_profile['damage']*.12,
                attack_cooldown_s=1/spec['rounds_per_s'],
                enchant_effects=enchant_contract.equipped_effects([row],int(self._progression.get('level',1)))+spec['status_effects'])
            result=combat_contract.resolve_attack(self._combat_state,attacker_id='player',defender_id=resolved_id,
                attacker_profile=player_profile,defender_profile=defender_profile,sim_time=self._sim_time,
                seed=seed,action_id='firearm_shot',cooldown_group=row['instance_id'])
            if not result.get('ok'):return finish(result)
        else:result=dict(ok=True,status='FIRED',damage=0,defeated=False,time_s=self._sim_time)
        mag['rounds']-=spec['rounds_per_shot'];mag['shots']+=1;mag['next_fire']=self._sim_time+cooldown
        self._firearm_last_hand=row['equipped_slot']
        flight=max(.04,min(1.5,distance/spec['speed_m_s']))
        shot=dict(id=row['instance_id']+':'+str(mag['shots']),time_s=self._sim_time,slot=row['equipped_slot'],
            construction=spec['construction'],ammo_id=spec['ammo_id'],color=spec['color'],shape=spec['shape'],
            start=start,target=target,flight_s=flight,projectiles=len(offsets),offsets=offsets,
            impact=bool(index is not None),silent=spec['construction']=='silenced',
            impact_size=.9 if spec['construction']=='rocket' else .35 if spec['construction'] in ('plasma','rail') else .15)
        shot['enchants']=enchant_contract.firearm_bursts(row,int(self._progression.get('level',1)))
        shot['enchant_colors']=list(dict.fromkeys(c for enchant in shot['enchants'] for c in enchant['colors']))[:6]
        self._firearm_shots=(getattr(self,'_firearm_shots',[])+[shot])[-24:]
        self._start_character_action_locked(
            "player", self._player_attack_animation_clip_locked("firearm_shot")
        )
        result.update(weapon_id=row['instance_id'],hand=row['equipped_slot'],ammo_id=spec['ammo_id'],
            rounds_consumed=spec['rounds_per_shot'],magazine_rounds=mag['rounds'],pellets_hit=hits,
            projectiles=len(offsets),distance_m=round(distance,3),cooldown_s=cooldown,shot=shot)
        if index is not None:
            self._start_character_action_locked(
                resolved_id, "Death" if result.get("defeated") else "HitReact"
            )
            result['faction']=factions_contract.adjust_person(self._faction_state,resolved_id,-30,
                source='PLAYER_ATTACK',sim_time=self._sim_time)
            identity_contract.record_memory(self._individual_state,resolved_id,'PLAYER_ATTACK','player',self._sim_time,
                text='The player shot at me; I will remember the threat.',weight=.92)
            if result.get('defeated'):result['defeat']=self._handle_npc_defeat_locked(resolved_id,index,result)
        self._append_event_locked('COMBAT_ATTACK','Fired '+spec['name']+'.',actor_id='player',
            subject_id=row['instance_id'],target_id=resolved_id,payload=copy.deepcopy(result))
        return finish(result)

    def attack(self, target_id: str = "", action_id: str = "basic_attack") -> dict[str, Any]:
        """Resolve equipped firearm, ranged wand or melee attacks on NPCs."""
        with self._lock:
            if self._services.get('taxi_flight'):return {'error':'TAXI_IN_PROGRESS'}
            if str(target_id or self._combat_target_id) in self._services['group']['members'] and not self._duel_opponent_locked(str(target_id or self._combat_target_id)):
                result=self.snapshot_locked();result['error']='COMBAT_FRIENDLY_GROUP_TARGET';return result
            if any(row.get('definition_id')=='item.weapon_pistol' for row in self._player_equipped_instances_locked()):
                return self._firearm_attack_locked(str(target_id or ''),action_id=='automatic_fire')
            self._ensure_combat_actors_locked()
            player_profile = self._player_combat_profile_locked()
            wand=next((row for row in self._player_equipped_instances_locked()
                if row.get('definition_id')=='item.weapon_wand' and row.get('equipped_slot')=='MAIN_HAND'),None)
            wand_spec=None
            if wand:
                from backend.game_engine_caster_designs import wand_profile
                wand_spec=wand_profile(item_state.item_appearance_index(wand['instance_id']))
                player_profile=dict(player_profile,attack_range_m=wand_spec['range_m'],
                    attack_cooldown_s=wand_spec['cooldown_s'],damage=player_profile['damage']+wand_spec['damage'],
                    enchant_effects=player_profile.get('enchant_effects',[])+wand_spec['status_effects'])
            player_actor = combat_contract.ensure_actor(
                self._combat_state,
                "player",
                player_profile,
            )
            if not player_actor.get("alive"):
                snapshot = self.snapshot_locked()
                result = {"error": "COMBAT_PLAYER_DEFEATED", "respawn_at": player_actor.get("respawn_at", 0.0)}
                snapshot["error"] = result["error"]
                snapshot["combat_result"] = result
                return snapshot

            self._target_view_locked()
            wanted = str(target_id or self._combat_target_id or "").strip()
            candidates: list[tuple[float, str, int]] = []
            for index in self._npc_indices[: npc_contract.MAX_NPCS]:
                if not self._alive[index] or not self._npc_ids[index]:
                    continue
                identity_id = str(self._npc_ids[index])
                if identity_id in self._services['group']['members'] and not self._duel_opponent_locked(identity_id):
                    continue
                if wanted and identity_id != wanted:
                    continue
                actor = self._combat_state.get("actors", {}).get(identity_id)
                if isinstance(actor, dict) and not actor.get("alive", True):
                    continue
                distance = math.hypot(self._x[index] - self._x[0], self._z[index] - self._z[0])
                candidates.append((distance, identity_id, index))
            candidates.sort(key=lambda row: (row[0], row[1]))
            if not candidates:
                snapshot = self.snapshot_locked()
                result = {
                    "error": "COMBAT_TARGET_REQUIRED",
                    "target_id": wanted,
                    "attack_range_m": player_profile.get("attack_range_m", 0.0),
                }
                snapshot["error"] = result["error"]
                snapshot["combat_result"] = result
                return snapshot
            distance, resolved_id, index = candidates[0]
            attack_range = float(player_profile.get("attack_range_m", 2.5))
            if distance > attack_range + 0.35:
                snapshot = self.snapshot_locked()
                result = {
                    "error": "COMBAT_TARGET_OUT_OF_RANGE",
                    "target_id": resolved_id,
                    "distance_m": round(distance, 3),
                    "attack_range_m": round(attack_range, 3),
                }
                snapshot["error"] = result["error"]
                snapshot["combat_result"] = result
                return snapshot
            if not self._npc_line_of_sight_locked(index):
                snapshot = self.snapshot_locked()
                result = {
                    "error": "COMBAT_LINE_OF_SIGHT_BLOCKED",
                    "target_id": resolved_id,
                    "distance_m": round(distance, 3),
                }
                snapshot["error"] = result["error"]
                snapshot["combat_result"] = result
                return snapshot
            people = self._individual_state.get("individuals", {})
            person = people.get(resolved_id) if isinstance(people, dict) else None
            npc_profile = self._npc_combat_profile_locked(resolved_id, person)
            result = combat_contract.resolve_attack(
                self._combat_state,
                attacker_id="player",
                defender_id=resolved_id,
                attacker_profile=player_profile,
                defender_profile=npc_profile,
                sim_time=self._sim_time,
                seed=self._tick * 17 + index * 31 + len(self._event_journal.get("events", [])),
                action_id=action_id,
            )
            result["distance_m"] = round(distance, 3)
            self._last_combat = copy.deepcopy(result)
            if result.get("ok"):
                self._start_character_action_locked(
                    "player", self._player_attack_animation_clip_locked(action_id)
                )
                self._start_character_action_locked(
                    resolved_id, "Death" if result.get("defeated") else "HitReact"
                )
                if wand_spec:
                    yaw=self._yaw[0]
                    shot=dict(id=wand['instance_id']+':cast:'+str(self._tick)+':'+str(self._sim_time),
                        kind='WAND',time_s=self._sim_time,slot='MAIN_HAND',construction='wand',
                        ammo_id='',color=wand_spec['colors'][0],shape='cell',
                        start=[self._x[0]+math.cos(yaw)*.38,self._y[0]+.7,self._z[0]-math.sin(yaw)*.38],
                        target=[self._x[index],self._y[index]+.25,self._z[index]],
                        flight_s=max(.08,min(1.2,distance/35)),projectiles=1,offsets=[[0,0]],
                        impact=True,silent=True,impact_size=.23,
                        enchants=enchant_contract.firearm_bursts(wand,int(self._progression.get('level',1))))
                    shot['enchant_colors']=list(dict.fromkeys(wand_spec['colors']+[c for e in shot['enchants'] for c in e['colors']]))[:6]
                    self._firearm_shots=(getattr(self,'_firearm_shots',[])+[shot])[-24:]
                    result['cast']=shot
                faction_result = factions_contract.adjust_person(
                    self._faction_state,
                    resolved_id,
                    -30,
                    source="PLAYER_ATTACK",
                    sim_time=self._sim_time,
                )
                result["faction"] = faction_result
                if isinstance(person, dict):
                    identity_contract.record_memory(
                        self._individual_state,
                        resolved_id,
                        "PLAYER_ATTACK",
                        "player",
                        self._sim_time,
                        text="The player attacked me; I will remember the threat.",
                        weight=0.92,
                    )
                self._append_event_locked(
                    "COMBAT_ATTACK",
                    f"Player hit {resolved_id} for {result.get('damage', 0)}.",
                    actor_id="player",
                    subject_id=str(action_id or "basic_attack"),
                    target_id=resolved_id,
                    payload=copy.deepcopy(result),
                )
                if result.get("defeated"):
                    result["defeat"] = self._handle_npc_defeat_locked(
                        resolved_id,
                        index,
                        result,
                    )
                self._last_combat = copy.deepcopy(result)
            snapshot = self.snapshot_locked()
            if not result.get("ok"):
                snapshot["error"] = result.get("status", "COMBAT_FAILED")
            snapshot["combat_result"] = copy.deepcopy(result)
            return snapshot

    def accept_quest(self, quest_id: str = "quest.shoreline-first") -> dict[str, Any]:
        """Accept a quest only from its real nearby authored giver."""
        with self._lock:
            wanted = str(quest_id or "quest.shoreline-first")
            definition = self._quest_catalog.get(wanted)
            if not isinstance(definition, dict):
                snapshot = self.snapshot_locked()
                snapshot["error"] = "QUEST_UNKNOWN"
                snapshot["quest_result"] = {"error": "QUEST_UNKNOWN", "quest_id": wanted}
                return snapshot
            giver_id = str(definition.get("giver_id", ""))
            giver_index = self._npc_index_for_id_locked(giver_id)
            if giver_index is None:
                snapshot = self.snapshot_locked()
                snapshot["error"] = "QUEST_GIVER_UNAVAILABLE"
                snapshot["quest_result"] = {"error": "QUEST_GIVER_UNAVAILABLE", "giver_id": giver_id}
                return snapshot
            distance = math.hypot(self._x[giver_index] - self._x[0], self._z[giver_index] - self._z[0])
            if distance > npc_contract.INTERACTION_RADIUS_M or not self._npc_line_of_sight_locked(giver_index):
                snapshot = self.snapshot_locked()
                result = {
                    "error": "QUEST_GIVER_OUT_OF_RANGE",
                    "giver_id": giver_id,
                    "distance_m": round(distance, 3),
                    "radius_m": npc_contract.INTERACTION_RADIUS_M,
                }
                snapshot["error"] = result["error"]
                snapshot["quest_result"] = result
                return snapshot
            ok, result = quests_contract.accept(
                self._quest_state,
                self._quest_catalog,
                wanted,
                self._sim_time,
            )
            if ok:
                identity_contract.record_memory(
                    self._individual_state,
                    giver_id,
                    "QUEST_GIVEN",
                    "player",
                    self._sim_time,
                    text=f"Gave quest {wanted} to the player.",
                    weight=0.72,
                )
                self._append_event_locked(
                    "QUEST_ACCEPT",
                    f"Player accepted {definition.get('name', wanted)} from {giver_id}.",
                    actor_id="player",
                    subject_id=wanted,
                    target_id=giver_id,
                    payload={"distance_m": round(distance, 3), "quest": copy.deepcopy(result)},
                )
            snapshot = self.snapshot_locked()
            if not ok:
                snapshot["error"] = result.get("error", "QUEST_ACCEPT_FAILED")
            result["distance_m"] = round(distance, 3)
            snapshot["quest_result"] = result
            return snapshot

    def claim_quest(self, quest_id: str = "") -> dict[str, Any]:
        """Claim one ready quest with atomic XP, currency and item rewards."""
        with self._lock:
            active = self._quest_state.get("active", {})
            wanted = str(quest_id or "")
            if not wanted and isinstance(active, dict):
                ready = [
                    key for key, row in active.items()
                    if isinstance(row, dict) and str(row.get("status")) == "READY"
                ]
                wanted = sorted(ready)[0] if ready else ""
            before_state = copy.deepcopy(self._quest_state)
            before_items = copy.deepcopy(self._item_instances)
            before_inventory = dict(self._inventory)
            before_progression = copy.deepcopy(self._progression)
            before_economy = copy.deepcopy(self._economy_state)
            before_factions = copy.deepcopy(self._faction_state)
            before_counter = self._item_counter
            try:
                ok, result = quests_contract.claim(
                    self._quest_state,
                    self._quest_catalog,
                    wanted,
                    self._sim_time,
                )
                if not ok:
                    snapshot = self.snapshot_locked()
                    snapshot["error"] = result.get("error", "QUEST_CLAIM_FAILED")
                    snapshot["quest_result"] = result
                    return snapshot
                rewards = result.get("rewards", {}) if isinstance(result.get("rewards"), dict) else {}
                reward_items = rewards.get("items", []) if isinstance(rewards.get("items"), list) else []
                inventory_slots = sum(
                    1
                    for row in self._item_instances.values()
                    if isinstance(row, dict)
                    and str(row.get("owner_id")) == "player"
                    and str(row.get("location")) == "INVENTORY"
                )
                if inventory_slots + len(reward_items) > item_state.MAX_INVENTORY_SLOTS:
                    raise ValueError("QUEST_REWARD_INVENTORY_FULL")
                wallet = self._economy_state.get("wallet")
                if not isinstance(wallet, dict):
                    raise ValueError("PLAYER_WALLET_MISSING")
                gold = max(0, int(rewards.get("gold", 0)))
                if int(wallet.get("gold", 0)) > economy_contract.MAX_CURRENCY - gold:
                    raise ValueError("PLAYER_GOLD_CAPACITY")
                reward_views: list[dict[str, Any]] = []
                for definition_id in reward_items:
                    if item_state.definition(self._item_catalog, definition_id) is None:
                        raise ValueError("QUEST_REWARD_DEFINITION_MISSING")
                    instance_id = self._next_item_instance_id_locked("quest-reward")
                    while instance_id in self._item_instances:
                        instance_id = self._next_item_instance_id_locked("quest-reward")
                    instance = item_state.make_instance(
                        self._item_catalog,
                        instance_id,
                        definition_id,
                        location="INVENTORY",
                        owner_id="player",
                        visual_phase=(self._item_counter % 17) * 0.31,
                    )
                    instance["origin"] = "QUEST_REWARD"
                    instance["roll_table_id"] = wanted
                    self._item_instances[instance_id] = instance
                    reward_views.append(
                        item_state.instance_view(
                            self._item_catalog,
                            instance,
                            sim_time=self._sim_time,
                        )
                    )
                xp_result = progression.grant_xp(self._progression, rewards.get("xp", 0))
                wallet["gold"] = economy_contract.bounded_currency(int(wallet.get("gold", 0)) + gold)
                wallet["earned"] = economy_contract.bounded_currency(int(wallet.get("earned", 0)) + gold)
                wallet["revision"] = max(0, int(wallet.get("revision", 0))) + 1
                faction_results = []
                faction_rewards = rewards.get("faction", {}) if isinstance(rewards.get("faction"), dict) else {}
                for faction_id, amount in list(faction_rewards.items())[: factions_contract.MAX_FACTIONS]:
                    faction_results.append(
                        factions_contract.adjust_player(
                            self._faction_state,
                            faction_id,
                            amount,
                            source="QUEST_REWARD",
                            sim_time=self._sim_time,
                        )
                    )
                self._inventory = item_state.inventory_counts(self._item_instances.values())
                result.update(
                    {
                        "reward_items": reward_views,
                        "xp_result": xp_result,
                        "faction_results": faction_results,
                        "gold_after": wallet["gold"],
                    }
                )
            except (TypeError, ValueError, KeyError, OverflowError) as exc:
                self._quest_state = before_state
                self._item_instances = before_items
                self._inventory = before_inventory
                self._progression = before_progression
                self._economy_state = before_economy
                self._faction_state = before_factions
                self._item_counter = before_counter
                snapshot = self.snapshot_locked()
                snapshot["error"] = "QUEST_CLAIM_ATOMIC_ROLLBACK"
                snapshot["quest_result"] = {"error": snapshot["error"], "cause": str(exc)[:96]}
                return snapshot
            self._append_event_locked(
                "QUEST_COMPLETE",
                f"Completed {wanted} and claimed its real rewards.",
                actor_id="player",
                subject_id=wanted,
                payload=copy.deepcopy(result),
            )
            snapshot = self.snapshot_locked()
            snapshot["quest_result"] = result
            return snapshot

    def activate_ability(self, ability_id: str = "ability.surge") -> dict[str, Any]:
        with self._lock:
            ok, result = self._activate_ability_locked(str(ability_id or "ability.surge"))
            snapshot = self.snapshot_locked()
            if not ok:
                snapshot["error"] = result.get("error", "ABILITY_FAILED")
            snapshot["ability_result"] = result
            return snapshot

    def claim_loot(self, seed: int | None = None) -> dict[str, Any]:
        with self._lock:
            self._loot_counter += 1
            roll_seed = (
                int(seed)
                if seed is not None
                else self._tick * 4099 + self._loot_counter
            )
            loot_roll = item_state.roll_loot(
                self._item_catalog,
                roll_seed,
                "loot.coastal_cache",
            )
            base_item_id = str(loot_roll.get("item_id", "item.island_compass"))
            rolled = content_catalog.deterministic_loot(
                self._content,
                roll_seed,
                base_item_id=base_item_id,
            )
            instance_id = f"loot-{self._loot_counter:04d}"
            rolled_instance = item_state.make_instance(
                self._item_catalog,
                instance_id,
                base_item_id,
                location="INVENTORY",
                quantity=int(loot_roll.get("quantity", 1)),
                owner_id="player",
                visual_phase=float(self._loot_counter) * 0.61,
            )
            rolled_instance.update(
                {
                    "seed": int(roll_seed),
                    "base_item_id": base_item_id,
                    "roll_table_id": str(loot_roll.get("table_id", "loot.coastal_cache")),
                    "roll": int(loot_roll.get("roll", 0)),
                    "affixes": list(rolled.get("affixes", [])),
                }
            )
            self._item_instances[instance_id] = rolled_instance
            self._inventory[base_item_id] = int(self._inventory.get(base_item_id, 0)) + int(
                rolled_instance["quantity"]
            )
            self._loot_items.append(rolled_instance)
            self._loot_items = self._loot_items[-64:]
            xp_result = progression.grant_xp(self._progression, 15)
            self._append_event_locked(
                "LOOT",
                f"{rolled_instance['name']} acquired ({rolled_instance['rarity'].lower()}).",
                actor_id="player",
                subject_id=instance_id,
                target_id=str(loot_roll.get("table_id", "loot.coastal_cache")),
                payload={
                    "seed": roll_seed,
                    "definition_id": base_item_id,
                    "rarity": rolled_instance.get("rarity", ""),
                    "quantity": rolled_instance.get("quantity", 1),
                    "roll": loot_roll.get("roll", 0),
                },
            )
            self._record_quest_event_locked(
                {
                    "kind": "PICKUP",
                    "target_id": instance_id,
                    "definition_id": base_item_id,
                    "rarity": str(rolled_instance.get("rarity", "COMMON")),
                    "amount": max(1, int(rolled_instance.get("quantity", 1))),
                }
            )
            snapshot = self.snapshot_locked()
            snapshot["loot_result"] = {"item": rolled_instance, "xp": xp_result}
            return snapshot

    def craft_recipe(self, recipe_id: str = "recipe.field_ration") -> dict[str, Any]:
        with self._lock:
            recipe=self._content.get('recipes',{}).get(str(recipe_id or 'recipe.field_ration'))
            if recipe and not self._profession_known_locked(recipe.get('profession','SURVIVAL')):
                return self._local_action_error_locked('PROFESSION_NOT_KNOWN')
            candidate = dict(self._inventory)
            ok, result = content_catalog.craft(
                self._content,
                str(recipe_id or "recipe.field_ration"),
                candidate,
            )
            if ok:
                error = self._craft_inventory_error_locked(candidate)
                if error:
                    ok, result = False, {'error': error, 'recipe_id': recipe_id}
            if ok:
                self._inventory = candidate
                self._reconcile_item_instances_locked()
            self._last_crafting = dict(result)
            if ok:
                self._append_event_locked(
                    "CRAFT",
                    f"Crafted {result.get('name', recipe_id)} from the shared content catalogue.",
                    actor_id="player",
                    subject_id=str(recipe_id or "recipe.field_ration"),
                    payload={
                        "recipe_id": result.get("recipe_id", recipe_id),
                        "outputs": result.get("outputs", {}),
                    },
                )
            else:
                self._append_event_locked(
                    "CRAFT_FAIL",
                    f"Craft failed: {result.get('error', 'unknown error')}.",
                    actor_id="player",
                    subject_id=str(recipe_id or "recipe.field_ration"),
                    payload={"error": result.get("error", "CRAFT_FAILED")},
                )
            snapshot = self.snapshot_locked()
            if not ok:
                snapshot["error"] = result.get("error", "CRAFT_FAILED")
            snapshot["craft_result"] = result
            return snapshot

    def _craft_enchant_scroll_locked(self, enchant_id: str, station_id: str) -> dict[str, Any]:
        """Create a persistent scroll at the real table; validate before spending."""
        definition = enchant_contract.definition(enchant_id)
        enchant_id = definition.get('id', enchant_id)
        error = ''
        station = self._gear_tables.get('workstations', {}).get('station.enchanting_altar', {})
        position = station.get('position', {})
        cost = enchant_contract.scroll_cost(definition) if definition else {}
        if not definition:
            error = 'ENCHANT_RECIPE_INVALID'
        elif not self._profession_known_locked('ENCHANTING'):
            error = 'PROFESSION_NOT_KNOWN'
        elif station_id != 'station.enchanting_altar' or not station:
            error = 'ENCHANT_TABLE_REQUIRED'
        elif math.dist((self._x[0], self._y[0], self._z[0]),
                (float(position.get('x', 0)),
                 self._terrain_height_locked(float(position.get('x', 0)), float(position.get('z', 0))) + .65,
                 float(position.get('z', 0)))) > item_state.INTERACTION_RADIUS_M:
            error = 'ENCHANT_TABLE_OUT_OF_REACH'
        elif int(self._progression.get('level', 1)) < definition['required_level']:
            error = 'ENCHANT_LEVEL_REQUIRED'
        elif len(self._item_instances) >= item_state.MAX_WORLD_INSTANCES or sum(
                1 for row in self._item_instances.values()
                if row.get('owner_id') == 'player' and row.get('location') == 'INVENTORY') >= item_state.MAX_INVENTORY_SLOTS:
            error = 'ITEM_INVENTORY_FULL'
        elif any(int(self._inventory.get(key, 0)) < amount for key, amount in cost.items()):
            error = 'GEAR_MATERIALS_MISSING'
        if error:
            snapshot = self.snapshot_locked()
            snapshot['error'] = error
            snapshot['gear_craft_result'] = dict(error=error, inputs=cost,
                required_level=definition.get('required_level', 1))
            return snapshot
        instance_id = self._next_item_instance_id_locked('enchant-scroll')
        while instance_id in self._item_instances:
            instance_id = self._next_item_instance_id_locked('enchant-scroll')
        row = item_state.make_instance(self._item_catalog, instance_id, 'item.enchant_scroll')
        row['scroll_enchant_id'] = enchant_id
        row = item_state.normalize_instance(self._item_catalog, row)
        # All validation is complete. Commit resources and the single scroll together.
        for key, amount in cost.items():
            self._inventory[key] -= amount
        self._item_instances[instance_id] = row
        self._inventory['item.enchant_scroll'] = self._inventory.get('item.enchant_scroll', 0) + 1
        self._reconcile_item_instances_locked()
        profession = self._profession_state.setdefault('ENCHANTING', dict(
            id='ENCHANTING', name='Enchanting', level=1, xp=0, max_level=100, specializations=[]))
        profession['xp'] += 15 * definition['tier']
        while profession['level'] < 100 and profession['xp'] >= profession['level'] * 100:
            profession['xp'] -= profession['level'] * 100
            profession['level'] += 1
        result = dict(action='CRAFT_ENCHANT_SCROLL', enchant_id=enchant_id,
            name=row['name'], station_id=station_id, inputs=cost,
            tier=definition['tier'], created=[item_state.instance_view(self._item_catalog, row)],
            profession=copy.deepcopy(profession))
        self._last_crafting = copy.deepcopy(result)
        self._append_event_locked('GEAR_CRAFT', 'Created ' + row['name'] + '.',
            actor_id='player', subject_id=instance_id, target_id=station_id, payload=result)
        self._record_quest_event_locked(dict(kind='CRAFT', target_id=instance_id,
            definition_id='item.enchant_scroll', amount=1, rarity=row['rarity']))
        snapshot = self.snapshot_locked()
        snapshot['gear_craft_result'] = result
        snapshot['craft_result'] = result
        return snapshot

    def craft_gear(
        self,
        recipe_id: str = "recipe.fiber_rope",
        station_id: str = "",
    ) -> dict[str, Any]:
        """Craft one station recipe and preserve its result as item instances."""
        with self._lock:
            wanted = str(recipe_id or "recipe.fiber_rope")
            if wanted.startswith('recipe.enchant_scroll.'):
                return self._craft_enchant_scroll_locked(
                    wanted.removeprefix('recipe.enchant_scroll.'), str(station_id or ''))
            recipe = self._gear_tables.get("recipes", {}).get(wanted, {})
            if wanted.startswith('recipe.ammo_') and recipe:
                station=self._gear_tables.get('workstations',{}).get('station.workbench',{})
                p=station.get('position',{})
                x=float(p.get('x',0));z=float(p.get('z',0))
                if station_id=='station.workbench' and math.dist((self._x[0],self._y[0],self._z[0]),
                        (x,self._terrain_height_locked(x,z)+.65,z))>item_state.INTERACTION_RADIUS_M:
                    snapshot=self.snapshot_locked();snapshot['error']='AMMO_WORKBENCH_OUT_OF_REACH'
                    snapshot['gear_craft_result']={'error':snapshot['error']}
                    return snapshot
            profession_id = str(recipe.get("profession", "SURVIVAL")) if isinstance(recipe, dict) else "SURVIVAL"
            if recipe and not self._profession_known_locked(profession_id):
                return self._local_action_error_locked('PROFESSION_NOT_KNOWN')
            profession = self._profession_state.get(profession_id, {})
            profession_level = max(1, int(profession.get("level", 1))) if isinstance(profession, dict) else 1
            before_ids = set(self._item_instances)
            candidate = dict(self._inventory)
            ok, result = gear_contract.craft(
                self._gear_tables,
                wanted,
                candidate,
                station_id=str(station_id or ""),
                profession_level=profession_level,
            )
            if ok:
                error = self._craft_inventory_error_locked(candidate)
                if error:
                    ok, result = False, {'error': error, 'recipe_id': wanted}
            if ok:
                self._inventory = candidate
                self._reconcile_item_instances_locked()
                profession_row = self._profession_state.setdefault(
                    str(result.get("profession", profession_id)),
                    {"id": str(result.get("profession", profession_id)), "name": str(result.get("profession", profession_id)), "level": 1, "xp": 0, "max_level": 100, "specializations": []},
                )
                profession_row["xp"] = max(0, int(profession_row.get("xp", 0))) + 10 + int(result.get("difficulty", 1)) * 5
                profession_row["level"] = max(1, min(100, int(profession_row.get("level", 1))))
                while profession_row["level"] < 100 and profession_row["xp"] >= profession_row["level"] * 100:
                    profession_row["xp"] -= profession_row["level"] * 100
                    profession_row["level"] += 1
                created: list[dict[str, Any]] = []
                output_ids = set(str(value) for value in result.get("outputs", {}))
                for instance_key in sorted(set(self._item_instances) - before_ids):
                    instance = self._item_instances.get(instance_key)
                    if not isinstance(instance, dict) or str(instance.get("definition_id")) not in output_ids:
                        continue
                    instance["craft_quality"] = str(result.get("quality", "STANDARD"))
                    gear_state = instance.get("gear")
                    if isinstance(gear_state, dict):
                        gear_state["quality"] = str(result.get("quality", "STANDARD"))
                        gear_contract.recalculate_gear(gear_state, self._gear_tables)
                    created.append(
                        item_state.instance_view(
                            self._item_catalog,
                            instance,
                            sim_time=self._sim_time,
                        )
                    )
                    if len(created) >= item_state.MAX_INVENTORY_SLOTS:
                        break
                result["created"] = created[:item_state.MAX_INVENTORY_SLOTS]
                result["profession"] = copy.deepcopy(profession_row)
                self._append_event_locked(
                    "GEAR_CRAFT",
                    f"Crafted {result.get('name', wanted)} at {result.get('station_id', 'station')}.",
                    actor_id="player",
                    subject_id=wanted,
                    target_id=str(result.get("station_id", station_id or "")),
                    payload={
                        "quality": result.get("quality", "STANDARD"),
                        "created_ids": [
                            row.get("instance_id")
                            for row in created
                            if isinstance(row, dict)
                        ],
                        "profession": result.get("profession", {}),
                    },
                )
                for created_item in created:
                    if not isinstance(created_item, dict):
                        continue
                    self._record_quest_event_locked(
                        {
                            "kind": "CRAFT",
                            "target_id": str(created_item.get("instance_id", "")),
                            "definition_id": str(created_item.get("definition_id", "")),
                            "rarity": str(created_item.get("rarity", "COMMON")),
                            "amount": 1,
                        }
                    )
            else:
                self._append_event_locked(
                    "GEAR_CRAFT_FAIL",
                    f"Gear craft failed: {result.get('error', 'unknown error')}.",
                    actor_id="player",
                    subject_id=wanted,
                    target_id=str(station_id or ""),
                    payload={"error": result.get("error", "GEAR_CRAFT_FAILED")},
                )
            self._last_crafting = dict(result)
            snapshot = self.snapshot_locked()
            if not ok:
                snapshot["error"] = result.get("error", "GEAR_CRAFT_FAILED")
            snapshot["gear_craft_result"] = result
            snapshot["craft_result"] = result
            return snapshot

    def socket_item(
        self,
        instance_id: str = "",
        insertable_id: str = "",
    ) -> dict[str, Any]:
        """Insert one owned rune/gem and activate an exact runeword if matched."""
        with self._lock:
            selected = self._select_player_gear_locked(str(instance_id or ""))
            if selected is None:
                snapshot = self.snapshot_locked()
                snapshot["error"] = "GEAR_SOCKET_TARGET_REQUIRED"
                snapshot["gear_result"] = {"error": snapshot["error"]}
                return snapshot
            if self._item_binding_locked(selected):return self._local_action_error_locked('ITEM_PENDING_CONFIRMATION')
            gear_state = selected.get("gear")
            if not isinstance(gear_state, dict):
                snapshot = self.snapshot_locked()
                snapshot["error"] = "GEAR_INSTANCE_REQUIRED"
                snapshot["gear_result"] = {"error": snapshot["error"]}
                return snapshot
            wanted = str(insertable_id or "")
            if not wanted:
                sequence = ("rune.tir", "rune.ort", "rune.tal")
                socket_count = len(gear_state.get("sockets", [])) if isinstance(gear_state.get("sockets"), list) else 0
                candidate_id = sequence[socket_count] if socket_count < len(sequence) else ""
                if candidate_id and int(self._inventory.get(candidate_id, 0)) > 0:
                    wanted = candidate_id
                else:
                    wanted = next(
                        (
                            key
                            for key in sorted(self._inventory)
                            if int(self._inventory.get(key, 0)) > 0
                            and isinstance(item_state.definition(self._item_catalog, key), dict)
                            and str(item_state.definition(self._item_catalog, key).get("kind")) in gear_contract.INSERTABLE_KINDS
                        ),
                        "",
                    )
            insertable = next(
                (
                    row
                    for row in self._item_instances.values()
                    if isinstance(row, dict)
                    and str(row.get("definition_id")) == wanted
                    and str(row.get("location")) == "INVENTORY"
                    and str(row.get("owner_id")) == "player"
                ),
                None,
            )
            if insertable is None:
                snapshot = self.snapshot_locked()
                result = {"error": "GEAR_INSERTABLE_OWNERSHIP_REQUIRED", "insertable_id": wanted}
                snapshot["error"] = result["error"]
                snapshot["gear_result"] = result
                return snapshot
            ok, result = gear_contract.insert_socket(
                gear_state,
                wanted,
                self._gear_tables,
            )
            if ok and self._consume_inventory_item_locked(insertable):
                result["item"] = item_state.instance_view(
                    self._item_catalog,
                    selected,
                    sim_time=self._sim_time,
                )
                result["insertable_id"] = wanted
                result["runeword"] = result.get("runeword")
                self._append_event_locked(
                    "SOCKET",
                    f"Inserted {wanted} into {selected.get('name', 'gear')}."
                    + (f" Runeword {result['runeword']['name']} awakened." if isinstance(result.get("runeword"), dict) else ""),
                    actor_id="player",
                    subject_id=str(selected.get("instance_id", "")),
                    target_id=wanted,
                    payload={
                        "socket_count": result.get("socket_count", 0),
                        "runeword_id": (
                            result.get("runeword", {}).get("id")
                            if isinstance(result.get("runeword"), dict)
                            else ""
                        ),
                    },
                )
            elif ok:
                # Roll back the socket when the matching inventory instance
                # disappeared between validation and consumption.
                gear_state["sockets"] = gear_state.get("sockets", [])[:-1]
                gear_contract.recalculate_gear(gear_state, self._gear_tables)
                result = {"error": "GEAR_INSERTABLE_CONSUME_FAILED", "insertable_id": wanted}
                ok = False
            if not ok:
                self._append_event_locked(
                    "SOCKET_FAIL",
                    f"Socketing failed: {result.get('error', 'unknown error')}."
                    ,
                    actor_id="player",
                    subject_id=str(selected.get("instance_id", "")),
                    target_id=wanted,
                    payload={"error": result.get("error", "GEAR_SOCKET_FAILED")},
                )
            snapshot = self.snapshot_locked()
            if not ok:
                snapshot["error"] = result.get("error", "GEAR_SOCKET_FAILED")
            snapshot["gear_result"] = result
            return snapshot

    def enchant_gear(
        self,
        instance_id: str = "",
        enchant_id: str = "",
    ) -> dict[str, Any]:
        """Apply one of the gear-table enchants to owned equipment."""
        with self._lock:
            selected = self._select_player_gear_locked(str(instance_id or ""))
            if selected is None:
                snapshot = self.snapshot_locked()
                snapshot["error"] = "GEAR_ENCHANT_TARGET_REQUIRED"
                snapshot["gear_result"] = {"error": snapshot["error"]}
                return snapshot
            if self._item_binding_locked(selected):return self._local_action_error_locked('ITEM_PENDING_CONFIRMATION')
            gear_state = selected.get("gear")
            category = str(gear_state.get("base_type", "")) if isinstance(gear_state, dict) else ""
            wanted = str(enchant_id or "")
            if not wanted:
                wanted = "enchant.aquatic_edge" if category in {"SWORD", "BOW", "DAGGER"} else "enchant.treasure_sense"
            definition = enchant_contract.definition(wanted)
            wanted = definition.get('id', wanted)
            scroll = None
            enchant_tables = self._gear_tables
            if definition:
                scroll = next((row for row in self._item_instances.values()
                    if row.get('scroll_enchant_id') == wanted and row.get('owner_id') == 'player'
                    and row.get('location') == 'INVENTORY'), None)
                error = ''
                if int(self._progression.get('level', 1)) < definition['required_level']:
                    error = 'ENCHANT_LEVEL_REQUIRED'
                elif scroll is None:
                    error = 'ENCHANT_SCROLL_REQUIRED'
                if error:
                    snapshot = self.snapshot_locked()
                    snapshot['error'] = error
                    snapshot['gear_result'] = dict(error=error, required_level=definition['required_level'])
                    return snapshot
                enchant_tables = dict(self._gear_tables,
                    enchantments=dict(self._gear_tables['enchantments'], **{wanted: definition}))
            working = copy.deepcopy(gear_state)
            ok, result = gear_contract.apply_enchant(working, wanted, enchant_tables)
            if ok and scroll is not None:
                if not self._consume_inventory_item_locked(scroll):
                    ok, result = False, dict(error='ENCHANT_SCROLL_CONSUME_FAILED')
                else:
                    result['consumed_scroll_id'] = scroll['instance_id']
            if ok:
                selected['gear'] = working
            if ok:
                result["item"] = item_state.instance_view(
                    self._item_catalog,
                    selected,
                    sim_time=self._sim_time,
                )
                self._append_event_locked(
                    "GEAR_ENCHANT",
                    f"Enchanted {selected.get('name', 'gear')} with {result['enchantment']['name']}."
                    ,
                    actor_id="player",
                    subject_id=str(selected.get("instance_id", "")),
                    target_id=wanted,
                    payload={
                        "stat": result.get("enchantment", {}).get("stat", ""),
                        "amount": result.get("enchantment", {}).get("amount", 0),
                    },
                )
            else:
                self._append_event_locked(
                    "GEAR_ENCHANT_FAIL",
                    f"Gear enchant failed: {result.get('error', 'unknown error')}."
                    ,
                    actor_id="player",
                    subject_id=str(selected.get("instance_id", "")),
                    target_id=wanted,
                    payload={"error": result.get("error", "GEAR_ENCHANT_FAILED")},
                )
            snapshot = self.snapshot_locked()
            if not ok:
                snapshot["error"] = result.get("error", "GEAR_ENCHANT_FAILED")
            snapshot["gear_result"] = result
            return snapshot

    def enchant_last_loot(self, enchant_id: str = "enchant.wayfinder") -> dict[str, Any]:
        with self._lock:
            if not self._loot_items:
                snapshot = self.snapshot_locked()
                snapshot["error"] = "CONTENT_ITEM_INSTANCE_REQUIRED"
                return snapshot
            item = self._loot_items[-1]
            ok, result = content_catalog.enchant_item(
                self._content,
                item,
                str(enchant_id or "enchant.wayfinder"),
            )
            if ok:
                self._append_event_locked(
                    "ENCHANT",
                    f"Enchanted {item.get('name', 'item')} with {result['enchantment']['name']}.",
                )
            else:
                self._append_event_locked(
                    "ENCHANT_FAIL",
                    f"Enchant failed: {result.get('error', 'unknown error')}.",
                )
            snapshot = self.snapshot_locked()
            if not ok:
                snapshot["error"] = result.get("error", "ENCHANT_FAILED")
            snapshot["enchant_result"] = result
            return snapshot

    def pickup_item(self, instance_id: str = "") -> dict[str, Any]:
        """Move the nearest reachable ground item into the player inventory."""
        with self._lock:
            if self._player_defeated_locked():return self._local_action_error_locked('PLAYER_DEFEATED')
            row, distance = self._nearest_item_locked(str(instance_id or ""))
            if row is None or str(row.get("kind")) == "CONTAINER":
                snapshot = self.snapshot_locked()
                result = {
                    "error": "ITEM_PICKUP_TARGET_REQUIRED",
                    "radius_m": item_state.INTERACTION_RADIUS_M,
                }
                snapshot["error"] = result["error"]
                snapshot["item_result"] = result
                return snapshot
            group = self._shared_group_loot_context_locked()
            if group and group.get('members') and group.get('loot_method') != 'freeforall':
                return self._open_shared_group_loot_source_locked(row)
            ok, transition = self._move_item_locked(
                row,
                "INVENTORY",
                owner_id="player",
            )
            if not ok:
                snapshot = self.snapshot_locked()
                snapshot["error"] = transition.get("error", "ITEM_PICKUP_FAILED")
                snapshot["item_result"] = transition
                return snapshot
            result = {
                "action": "PICKUP",
                "distance_m": round(distance, 3),
                "item": item_state.instance_view(
                    self._item_catalog,
                    row,
                    sim_time=self._sim_time,
                ),
            }
            self._last_item_interaction = result
            self._append_event_locked(
                "ITEM_PICKUP",
                f"Picked up {row.get('name', 'item')}.",
                actor_id="player",
                subject_id=str(row.get("instance_id", "")),
                payload={
                    "definition_id": row.get("definition_id", ""),
                    "location": row.get("location", ""),
                },
            )
            self._record_quest_event_locked(
                {
                    "kind": "PICKUP",
                    "target_id": str(row.get("instance_id", "")),
                    "definition_id": str(row.get("definition_id", "")),
                    "rarity": str(row.get("rarity", "COMMON")),
                    "amount": max(1, int(row.get("quantity", 1))),
                }
            )
            snapshot = self.snapshot_locked()
            snapshot["item_result"] = result
            return snapshot

    def open_container(self, instance_id: str = "") -> dict[str, Any]:
        """Open one nearby container while keeping its contents in the world state."""
        with self._lock:
            if self._player_defeated_locked():return self._local_action_error_locked('PLAYER_DEFEATED')
            row, distance = self._nearest_item_locked(
                str(instance_id or ""),
                container_only=True,
            )
            if row is None:
                snapshot = self.snapshot_locked()
                result = {
                    "error": "ITEM_CONTAINER_TARGET_REQUIRED",
                    "radius_m": item_state.INTERACTION_RADIUS_M,
                }
                snapshot["error"] = result["error"]
                snapshot["item_result"] = result
                return snapshot
            state = str(row.get("container_state", "CLOSED")).upper()
            if state == "CLOSED":
                row["container_state"] = "OPEN"
                self._append_event_locked(
                    "CONTAINER_OPEN",
                    f"Opened {row.get('name', 'container')}; contents are inspectable.",
                    actor_id="player",
                    subject_id=str(row.get("instance_id", "")),
                    payload={"container_state": row.get("container_state", "OPEN")},
                )
            if str(row.get("definition_id")) == "container.supply_crate":
                self._open_stash_container_id = str(row.get("instance_id"))
                self._open_merchant_id = ""
                try:
                    self._stash_state = self._stash_store.load(self._account_id)
                    self._stash_error = ""
                except (OSError, ValueError) as exc:
                    self._stash_error = type(exc).__name__ + ":" + str(exc)
            self._open_loot_locked(row)
            result = {
                "action": "OPEN",
                "distance_m": round(distance, 3),
                "container": item_state.instance_view(
                    self._item_catalog,
                    row,
                    sim_time=self._sim_time,
                ),
            }
            self._last_item_interaction = result
            snapshot = self.snapshot_locked()
            snapshot["item_result"] = result
            return snapshot

    def loot_container(self, instance_id: str = "") -> dict[str, Any]:
        """Transfer all bounded contents from one nearby openable cache."""
        with self._lock:
            if self._player_defeated_locked():return self._local_action_error_locked('PLAYER_DEFEATED')
            row, distance = self._nearest_item_locked(
                str(instance_id or ""),
                container_only=True,
            )
            if row is None:
                snapshot = self.snapshot_locked()
                result = {
                    "error": "ITEM_CONTAINER_TARGET_REQUIRED",
                    "radius_m": item_state.INTERACTION_RADIUS_M,
                }
                snapshot["error"] = result["error"]
                snapshot["item_result"] = result
                return snapshot
            group = self._shared_group_loot_context_locked()
            if group and group.get('members') and group.get('loot_method') != 'freeforall':
                return self._open_shared_group_loot_source_locked(row)
            row["container_state"] = "OPEN"
            contents = [
                child
                for child in self._item_instances.values()
                if isinstance(child, dict)
                and str(child.get("location")) == "CONTAINER"
                and str(child.get("container_id")) == str(row.get("instance_id"))
            ][: item_state.MAX_CONTAINER_ITEMS]
            moved: list[dict[str, Any]] = []
            for child in contents:
                ok, _ = self._move_item_locked(child, "INVENTORY", owner_id="player")
                if ok:
                    moved.append(
                        item_state.instance_view(
                            self._item_catalog,
                            child,
                            sim_time=self._sim_time,
                        )
                    )
            remaining = [
                child for child in contents
                if str(child.get("location")) == "CONTAINER"
            ]
            row["contents"] = [str(child.get("instance_id")) for child in remaining]
            row["container_state"] = "OPEN" if remaining else "LOOTED"
            result = {
                "action": "LOOT",
                "distance_m": round(distance, 3),
                "container_id": str(row.get("instance_id")),
                "items": moved,
                "count": len(moved),
            }
            self._last_item_interaction = result
            self._append_event_locked(
                "CONTAINER_LOOT",
                f"Looted {len(moved)} item(s) from {row.get('name', 'container')}.",
                actor_id="player",
                subject_id=str(row.get("instance_id", "")),
                payload={
                    "count": len(moved),
                    "item_ids": [
                        item.get("instance_id")
                        for item in moved
                        if isinstance(item, dict)
                    ],
                },
            )
            for moved_item in moved:
                if not isinstance(moved_item, dict):
                    continue
                self._record_quest_event_locked(
                    {
                        "kind": "PICKUP",
                        "target_id": str(moved_item.get("instance_id", "")),
                        "definition_id": str(moved_item.get("definition_id", "")),
                        "rarity": str(moved_item.get("rarity", "COMMON")),
                        "amount": max(1, int(moved_item.get("quantity", 1))),
                    }
                )
            snapshot = self.snapshot_locked()
            snapshot["item_result"] = result
            return snapshot

    def equip_item(self, instance_id: str = "", slot: str = "", *, _bind_confirmed=False) -> dict[str, Any]:
        with self._lock:
            return self._equipment_transaction_locked(lambda:self._equip_item_locked(instance_id,slot,_bind_confirmed=_bind_confirmed))

    def _equipment_transaction_locked(self,action):
        if getattr(self,'_service_atomic_active',False):return action()
        fields=('_item_instances','_inventory','_quest_state','_combat_state','_event_journal','_events',
                '_last_item_interaction','_persistence_revision')
        backup={key:copy.deepcopy(getattr(self,key)) for key in fields}
        self._service_atomic_active=True
        try:
            result=action()
            if result.get('error'):raise ValueError(result['error'])
            if self._item_instances!=backup['_item_instances'] or self._quest_state!=backup['_quest_state']:
                self.save_state(snapshot=False)
            return result
        except (ValueError,TypeError,KeyError,OverflowError,OSError) as error:
            for key,value in backup.items():setattr(self,key,value)
            self._loot_items=[self._item_instances[r['instance_id']] for r in self._loot_items if r['instance_id'] in self._item_instances]
            self._ui_snapshot_base=None;self._render_snapshot_cache=None
            code='ITEM_EQUIPMENT_SAVE_FAILED' if isinstance(error,OSError) else str(error)
            result=self._local_action_error_locked(code);result['item_result']={'error':code}
            return result
        finally:self._service_atomic_active=False

    def _equip_item_locked(self, instance_id: str = "", slot: str = "", *, _bind_confirmed=False) -> dict[str, Any]:
        """Equip a nearby inventory item by slot, replacing the previous item."""
        with self._lock:
            if self._player_defeated_locked():return self._local_action_error_locked('PLAYER_DEFEATED')
            selected = self._item_instance_locked(str(instance_id or ""))
            if selected is None or str(selected.get("location")) != "INVENTORY" or str(selected.get("owner_id")) != "player":
                if instance_id:
                    snapshot = self.snapshot_locked()
                    snapshot["error"] = "ITEM_EQUIP_TARGET_REQUIRED"
                    snapshot["item_result"] = {"error": snapshot["error"]}
                    return snapshot
                selected = None
                for key in sorted(self._item_instances):
                    candidate = self._item_instances[key]
                    definition = item_state.definition(self._item_catalog, candidate.get("definition_id"))
                    if (
                        isinstance(candidate, dict)
                        and str(candidate.get("location")) == "INVENTORY"
                        and str(candidate.get("owner_id")) == "player"
                        and isinstance(definition, dict)
                        and definition.get("equip_slot")
                    ):
                        selected = candidate
                        break
            definition = item_state.definition(self._item_catalog, selected.get("definition_id")) if selected else None
            requested_slot=str(slot or '').strip().upper()
            allowed=item_state.allowed_equip_slots(self._item_catalog,selected.get('definition_id'),selected.get('instance_id')) if selected else []
            slot = requested_slot or (str(definition.get("equip_slot", "")) if isinstance(definition, dict) else "")
            if requested_slot and requested_slot not in allowed:
                snapshot=self.snapshot_locked()
                snapshot['error']='ITEM_EQUIP_SLOT_INCOMPATIBLE'
                snapshot['item_result']={'error':snapshot['error'],'slot':requested_slot}
                return snapshot
            if not requested_slot and allowed==['MAIN_HAND','OFF_HAND']:
                # A second small gun chooses the other hand. Explicit drag
                # and hand buttons can always replace a chosen slot.
                worn={str(row.get('equipped_slot')):row for row in self._player_equipped_instances_locked()}
                main=worn.get('MAIN_HAND',{})
                if main.get('definition_id')==selected.get('definition_id') and item_state.equipment_wielding(main)!='2H' and worn.get('OFF_HAND',{}).get('definition_id')!=selected.get('definition_id'):
                    slot='OFF_HAND'
            if selected is None or not slot:
                snapshot = self.snapshot_locked()
                result = {"error": "ITEM_EQUIP_TARGET_REQUIRED"}
                snapshot["error"] = result["error"]
                snapshot["item_result"] = result
                return snapshot
            worn=self._player_equipped_instances_locked()
            if int(definition.get('required_level',0))>self._progression.get('level',1):
                return self._local_action_error_locked('ITEM_LEVEL_REQUIRED')
            if selected.get('bound_to') and selected['bound_to']!=str(self._persistence_key):
                return self._local_action_error_locked('ITEM_BOUND_TO_ANOTHER_CHARACTER')
            if slot=='OFF_HAND' and any(row.get('equipped_slot')=='MAIN_HAND' and item_state.equipment_wielding(row)=='2H' for row in worn):
                snapshot=self.snapshot_locked();snapshot['error']='ITEM_EQUIP_TWO_HANDS_OCCUPIED'
                snapshot['item_result']={'error':snapshot['error']}
                return snapshot
            two_handed=item_state.equipment_wielding(selected)=='2H'
            replaced = []
            for equipped in list(self._item_instances.values()):
                if (
                    equipped is not selected
                    and str(equipped.get("location")) == "EQUIPPED"
                    and str(equipped.get("owner_id")) == "player"
                    and (str(equipped.get("equipped_slot")) == slot or (two_handed and str(equipped.get('equipped_slot'))=='OFF_HAND'))
                ):
                    replaced.append(equipped)
            inventory_count=sum(row.get('owner_id')=='player' and row.get('location')=='INVENTORY' for row in self._item_instances.values())
            if inventory_count-1+len(replaced)>item_state.MAX_INVENTORY_SLOTS:
                snapshot=self.snapshot_locked();snapshot['error']='ITEM_INVENTORY_FULL'
                snapshot['item_result']={'error':snapshot['error']}
                return snapshot
            self._ensure_inventory_slots_locked()
            source_slot=int(selected.get('slot_index',-1))
            replaced.sort(key=lambda r:r.get('equipped_slot')!=slot)
            if not _bind_confirmed and self._item_binding_needed_locked(selected,'EQUIP'):
                self._ensure_inventory_slots_locked()
                return self._item_binding_request_locked('ItemBindingEquip',selected,slot,
                    popup='EQUIP_BIND_CONFIRM' if requested_slot else 'AUTOEQUIP_BIND_CONFIRM')
            ok, transition = self._move_item_locked(
                selected,
                "EQUIPPED",
                owner_id="player",
                equipped_slot=slot,
            )
            if not ok:
                snapshot = self.snapshot_locked()
                snapshot["error"] = transition.get("error", "ITEM_EQUIP_FAILED")
                snapshot["item_result"] = transition
                return snapshot
            for n,previous in enumerate(replaced):
                moved, previous_transition = self._move_item_locked(
                    previous, "INVENTORY", owner_id="player"
                )
                if not moved:
                    self._move_item_locked(selected, "INVENTORY", owner_id="player")
                    snapshot = self.snapshot_locked()
                    snapshot["error"] = previous_transition.get("error", "ITEM_EQUIP_FAILED")
                    snapshot["item_result"] = previous_transition
                    return snapshot
                if n==0 and source_slot>=0:previous['slot_index']=source_slot
            result = {
                "action": "EQUIP",
                "slot": slot,
                "item": item_state.instance_view(
                    self._item_catalog,
                    selected,
                    sim_time=self._sim_time,
                ),
            }
            self._last_item_interaction = result
            self._append_event_locked(
                "ITEM_EQUIP",
                f"Equipped {selected.get('name', 'item')}.",
                actor_id="player",
                subject_id=str(selected.get("instance_id", "")),
                target_id=slot,
                payload={"slot": slot, "location": selected.get("location", "")},
            )
            self._record_quest_event_locked(
                {
                    "kind": "EQUIP",
                    "target_id": str(selected.get("instance_id", "")),
                    "definition_id": str(selected.get("definition_id", "")),
                    "rarity": str(selected.get("rarity", "COMMON")),
                    "amount": 1,
                }
            )
            snapshot = self.snapshot_locked()
            snapshot["item_result"] = result
            return snapshot

    def drop_item(self, instance_id: str = "") -> dict[str, Any]:
        """Drop one owned item in front of the player as a persistent world item."""
        with self._lock:
            if self._player_defeated_locked():return self._local_action_error_locked('PLAYER_DEFEATED')
            selected = self._item_instance_locked(str(instance_id or ""))
            if selected is None or not self._item_owned_state(
                selected.get("location"), selected.get("owner_id")
            ):
                if instance_id:
                    snapshot = self.snapshot_locked()
                    snapshot["error"] = "ITEM_DROP_TARGET_REQUIRED"
                    snapshot["item_result"] = {"error": snapshot["error"]}
                    return snapshot
                selected = next(
                    (
                        row
                        for row in self._item_instances.values()
                        if isinstance(row, dict)
                        and self._item_owned_state(row.get("location"), row.get("owner_id"))
                    ),
                    None,
                )
            if selected is None:
                snapshot = self.snapshot_locked()
                result = {"error": "ITEM_DROP_TARGET_REQUIRED"}
                snapshot["error"] = result["error"]
                snapshot["item_result"] = result
                return snapshot
            facing = controller.character_basis(self._yaw[0])
            if selected.get('bound_to'):return self._local_action_error_locked('ITEM_BOUND_CANNOT_DROP')
            position = {
                "x": self._x[0] + facing["forward"][0] * 1.6,
                "y": 0.0,
                "z": self._z[0] + facing["forward"][1] * 1.6,
            }
            position["y"] = self._terrain_height_locked(position["x"], position["z"])
            ok, transition = self._move_item_locked(
                selected,
                "GROUND",
                owner_id="",
                position=position,
            )
            if not ok:
                snapshot = self.snapshot_locked()
                snapshot["error"] = transition.get("error", "ITEM_DROP_FAILED")
                snapshot["item_result"] = transition
                return snapshot
            result = {
                "action": "DROP",
                "item": item_state.instance_view(
                    self._item_catalog,
                    selected,
                    sim_time=self._sim_time,
                ),
            }
            self._last_item_interaction = result
            self._append_event_locked(
                "ITEM_DROP",
                f"Dropped {selected.get('name', 'item')}.",
                actor_id="player",
                subject_id=str(selected.get("instance_id", "")),
                target_id="GROUND",
                payload={"position": position},
            )
            snapshot = self.snapshot_locked()
            snapshot["item_result"] = result
            return snapshot

    def unequip_item(self, instance_id: str) -> dict[str, Any]:
        with self._lock:
            return self._equipment_transaction_locked(lambda:self._unequip_item_locked(instance_id))

    def _unequip_item_locked(self, instance_id: str) -> dict[str, Any]:
        """Move one worn item back to the one-bag inventory."""
        with self._lock:
            if self._player_defeated_locked():return self._local_action_error_locked('PLAYER_DEFEATED')
            selected = self._item_instance_locked(str(instance_id or ""))
            if not selected or str(selected.get("location")) != "EQUIPPED" or str(selected.get("owner_id")) != "player":
                snapshot = self.snapshot_locked()
                snapshot["error"] = "ITEM_UNEQUIP_TARGET_REQUIRED"
                return snapshot
            ok, result = self._move_item_locked(selected, "INVENTORY", owner_id="player")
            if not ok:
                snapshot = self.snapshot_locked()
                snapshot["error"] = result.get("error", "ITEM_UNEQUIP_FAILED")
                return snapshot
            self._last_item_interaction = {"action": "UNEQUIP", "name": selected.get("name", "")}
            self._append_event_locked("ITEM_UNEQUIP", f"Unequipped {selected.get('name', 'item')}.")
            snapshot = self.snapshot_locked()
            snapshot["item_result"] = dict(self._last_item_interaction)
            return snapshot

    def move_inventory_slot(self, instance_id: str, slot_index: int) -> dict[str, Any]:
        """Rearrange one-bag cells without changing ownership or item state."""
        with self._lock:
            if self._player_defeated_locked():return self._local_action_error_locked('PLAYER_DEFEATED')
            self._ensure_inventory_slots_locked()
            selected = self._item_instance_locked(str(instance_id or ""))
            target = _safe_int(slot_index, -1)
            if not selected or str(selected.get("location")) != "INVENTORY" or str(selected.get("owner_id")) != "player" or not 0 <= target < item_state.MAX_INVENTORY_SLOTS:
                snapshot = self.snapshot_locked()
                snapshot["error"] = "ITEM_INVENTORY_SLOT_INVALID"
                return snapshot
            previous = int(selected.get("slot_index", -1))
            if self._item_binding_locked(selected):return self._local_action_error_locked('ITEM_PENDING_CONFIRMATION')
            for row in self._item_instances.values():
                if row is not selected and isinstance(row, dict) and str(row.get("location")) == "INVENTORY" and str(row.get("owner_id")) == "player" and int(row.get("slot_index", -1)) == target:
                    if self._item_binding_locked(row):return self._local_action_error_locked('ITEM_PENDING_CONFIRMATION')
                    definition=item_state.definition(self._item_catalog,selected.get('definition_id')) or {}
                    if int(definition.get('stack_limit',1))>1 and self._stacks_compatible(selected,row):
                        return self.transfer_inventory_stack(str(selected['instance_id']),target,0)
                    row["slot_index"] = previous
                    break
            selected["slot_index"] = target
            self._sync_saved_player_items_locked()
            snapshot = self.snapshot_locked()
            snapshot["item_result"] = {"action": "BAG_MOVE", "name": selected.get("name", "")}
            return snapshot

    def move_equipment_to_inventory(self, instance_id: str, slot_index: int) -> dict[str, Any]:
        with self._lock:
            return self._equipment_transaction_locked(lambda:self._move_equipment_to_inventory_locked(instance_id,slot_index))

    def _move_equipment_to_inventory_locked(self, instance_id: str, slot_index: int) -> dict[str, Any]:
        """Place a worn item in one bag cell, swapping compatible gear under the same lock."""
        with self._lock:
            self._ensure_inventory_slots_locked()
            selected=self._item_instance_locked(str(instance_id or ""));target=_safe_int(slot_index,-1)
            if not selected or selected.get("location")!="EQUIPPED" or selected.get("owner_id")!="player" or not 0<=target<item_state.MAX_INVENTORY_SLOTS:
                snapshot=self.snapshot_locked();snapshot["error"]="ITEM_EQUIPMENT_MOVE_INVALID";return snapshot
            occupied=next((row for row in self._item_instances.values() if row.get("location")=="INVENTORY" and row.get("owner_id")=="player" and int(row.get("slot_index",-1))==target),None)
            if occupied:
                result=self.equip_item(str(occupied["instance_id"]),str(selected.get("equipped_slot","")))
            else:result=self.unequip_item(str(selected["instance_id"]))
            if result.get("error"):return result
            if any(e['event'] in ('EQUIP_BIND_CONFIRM','AUTOEQUIP_BIND_CONFIRM') for e in result.get('client_events',[])):return result
            return self.move_inventory_slot(str(selected["instance_id"]),target)

    @staticmethod
    def _stacks_compatible(left, right):
        ignored={'instance_id','quantity','slot_index','position','visual_phase','custody_origin'}
        return {k:v for k,v in left.items() if k not in ignored}=={k:v for k,v in right.items() if k not in ignored}

    def transfer_inventory_stack(self, instance_id: str, slot_index: int, count: int) -> dict[str, Any]:
        """Split or merge an exact owned stack; count=0 moves as much as fits."""
        with self._lock:
            if self._player_defeated_locked():return self._local_action_error_locked('PLAYER_DEFEATED')
            self._ensure_inventory_slots_locked()
            selected=self._item_instance_locked(str(instance_id or ""))
            def reject(reason):
                snapshot=self.snapshot_locked();snapshot['error']=reason;return snapshot
            if self._item_binding_locked(selected):return reject('ITEM_PENDING_CONFIRMATION')
            if (not selected or selected.get('location')!='INVENTORY' or selected.get('owner_id')!='player'
                    or type(slot_index) is not int or not 0<=slot_index<item_state.MAX_INVENTORY_SLOTS
                    or type(count) is not int or not 0<=count<=int(selected.get('quantity',1))):
                return reject('ITEM_STACK_TRANSFER_INVALID')
            if int(selected.get('slot_index',-1))==slot_index:return reject('ITEM_STACK_SAME_SLOT')
            target=next((r for r in self._item_instances.values() if r.get('location')=='INVENTORY'
                and r.get('owner_id')=='player' and int(r.get('slot_index',-1))==slot_index),None)
            if self._item_binding_locked(target):return reject('ITEM_PENDING_CONFIRMATION')
            definition=item_state.definition(self._item_catalog,selected.get('definition_id')) or {}
            limit=max(1,int(definition.get('stack_limit',1)));quantity=int(selected.get('quantity',1))
            if count==0:count=min(quantity,max(0,limit-int(target.get('quantity',1)))) if target else quantity
            if count==0:return reject('ITEM_STACK_CAPACITY')
            if target:
                # GG state such as condition/enchantment must never disappear in a merge.
                if not self._stacks_compatible(selected,target):return reject('ITEM_STACK_INCOMPATIBLE')
                if int(target.get('quantity',1))+count>limit:return reject('ITEM_STACK_CAPACITY')
                target['quantity']=int(target.get('quantity',1))+count
                selected['quantity']=quantity-count
                if not selected['quantity']:self._item_instances.pop(str(selected['instance_id']))
            elif count==quantity:selected['slot_index']=slot_index
            else:
                if limit<=1:return reject('ITEM_NOT_STACKABLE')
                if len(self._item_instances)>=item_state.MAX_WORLD_INSTANCES:return reject('ITEM_WORLD_CAPACITY')
                identity=self._next_item_instance_id_locked('inventory-split')
                while identity in self._item_instances:identity=self._next_item_instance_id_locked('inventory-split')
                new=copy.deepcopy(selected);new.update(instance_id=identity,quantity=count,slot_index=slot_index)
                # A child stack is a new physical instance. Retain the parent
                # lineage, but never assign it to two registry rows.
                new.pop('custody_origin',None)
                character=getattr(self,'_local_character_id','')
                if character:new['custody_origin']=item_state.normalize_custody_origin(dict(character=character,instance=identity))
                selected['quantity']=quantity-count;self._item_instances[identity]=new
            self._sync_saved_player_items_locked()
            self._append_event_locked('ITEM_STACK_TRANSFER',f"Moved {count} units of {selected.get('name','item')}.")
            snapshot=self.snapshot_locked();snapshot['item_result']={'action':'STACK_TRANSFER','count':count,'slot_index':slot_index};return snapshot

    def interact_item(self) -> dict[str, Any]:
        """Dispatch the nearest item interaction using the same target contract as UI."""
        with self._lock:
            stash = self._stash_view_locked()
            if stash.get("focused") and self._vehicle_kind == "NONE":
                return self.open_container(str(stash.get("container_id", "")))
            row, _ = self._nearest_item_locked()
            if row is None:
                snapshot = self.snapshot_locked()
                result = {
                    "error": "ITEM_INTERACTION_TARGET_REQUIRED",
                    "radius_m": item_state.INTERACTION_RADIUS_M,
                }
                snapshot["error"] = result["error"]
                snapshot["item_result"] = result
                return snapshot
            if str(row.get("kind")) == "CONTAINER":
                if str(row.get("definition_id")) == "container.supply_crate":
                    return self.open_container(str(row.get("instance_id")))
                if str(row.get("container_state", "CLOSED")) == "CLOSED":
                    return self.open_container(str(row.get("instance_id")))
                return self.loot_container(str(row.get("instance_id")))
            return self.pickup_item(str(row.get("instance_id")))

    def _stash_access_locked(self) -> bool:
        if self._player_defeated_locked():return False
        if not self._open_stash_container_id or self._stash_error:
            return False
        row, _ = self._nearest_item_locked(
            self._open_stash_container_id, container_only=True
        )
        return bool(
            row is not None
            and str(row.get("definition_id")) == "container.supply_crate"
            and str(row.get("container_state")) != "CLOSED"
        )

    def _stash_view_locked(self) -> dict[str, Any]:
        rows = self._stash_state.get("items", [])
        nearby = None
        nearest_distance = float("inf")
        for row in self._item_instances.values():
            if not isinstance(row, dict) or str(row.get("location")) != "GROUND" or not self._instance_item_visible_locked(row):
                continue
            if str(row.get("definition_id")) != "container.supply_crate":
                continue
            position = row.get("position") or {}
            distance = math.hypot(
                _clamp(position.get("x"), -1_000_000, 1_000_000) - self._x[0],
                _clamp(position.get("z"), -1_000_000, 1_000_000) - self._z[0],
            )
            if distance < nearest_distance:
                nearby, nearest_distance = row, distance
        container_id = str(nearby.get("instance_id", "")) if nearby else ""
        in_reach = nearby is not None and nearest_distance <= item_state.INTERACTION_RADIUS_M
        focused = False
        if in_reach:
            position = nearby.get("position") or {}
            forward = controller.character_basis(self._yaw[0])["forward"]
            dx = _clamp(position.get("x"), -1_000_000, 1_000_000) - self._x[0]
            dz = _clamp(position.get("z"), -1_000_000, 1_000_000) - self._z[0]
            focused = (dx * forward[0] + dz * forward[1]) / max(0.01, nearest_distance) >= 0.4
        return {
            "schema": mmo.STASH_SCHEMA,
            "capacity": mmo.MAX_STASH_SLOTS,
            "revision": max(0, _safe_int(self._stash_state.get("revision"))),
            "accessible": self._stash_access_locked(),
            "nearby": in_reach,
            "focused": focused,
            "container_id": container_id,
            "loot_count": sum(
                1 for row in self._item_instances.values()
                if isinstance(row, dict)
                and str(row.get("location")) == "CONTAINER"
                and str(row.get("container_id")) == container_id
            ) if container_id else 0,
            "items": [
                item_state.instance_view(self._item_catalog, row, include_visual=False)
                for row in rows[:mmo.MAX_STASH_SLOTS]
                if isinstance(row, dict)
            ],
            "error": self._stash_error,
        }

    def deposit_to_stash(self, instance_id: str, slot_index: int = -1) -> dict[str, Any]:
        with self._lock:
            selected = self._item_instance_locked(str(instance_id or ""))
            error = ""
            if not self._stash_access_locked():
                error = self._stash_error or "ACCOUNT_STASH_OUT_OF_REACH"
            elif not selected or str(selected.get("location")) not in {"INVENTORY", "EQUIPPED"} or str(selected.get("owner_id")) != "player":
                error = "ACCOUNT_STASH_INVENTORY_ITEM_REQUIRED"
            elif str(selected.get("kind")) == "CONTAINER":
                error = "ACCOUNT_STASH_CONTAINER_FORBIDDEN"
            elif self._item_binding_locked(selected):
                error = 'ITEM_PENDING_CONFIRMATION'
            elif selected.get('bound_to') and selected['bound_to']!=str(self._persistence_key):
                error = 'ITEM_BOUND_TO_ANOTHER_CHARACTER'
            if error:
                snapshot = self.snapshot_locked()
                snapshot["error"] = error
                return snapshot
            stored = copy.deepcopy(selected)
            item_state.transition_instance(stored, "BANK", owner_id=self._account_id)
            try:
                result = self._stash_store.deposit(self._account_id, stored, _safe_int(slot_index, -1))
            except (OSError, ValueError) as exc:
                self._stash_error = type(exc).__name__ + ":" + str(exc)
                result = {"error": self._stash_error}
            if result.get("error"):
                if isinstance(result.get("items"), list):
                    self._stash_state = result
                snapshot = self.snapshot_locked()
                snapshot["error"] = result["error"]
                return snapshot
            self._stash_state = result
            self._move_item_locked(selected, "BANK", owner_id=self._account_id)
            self._item_instances.pop(str(selected.get("instance_id")), None)
            self._last_item_interaction = {"action": "BANK_DEPOSIT", "name": selected.get("name", "")}
            self._append_event_locked("BANK_DEPOSIT", f"Stored {selected.get('name', 'item')} in the shared chest.")
            self._sync_saved_player_items_locked()
            snapshot = self.snapshot_locked()
            snapshot["item_result"] = dict(self._last_item_interaction)
            return snapshot

    def withdraw_from_stash(self, instance_id: str, slot_index: int = -1) -> dict[str, Any]:
        with self._lock:
            error = ""
            if not self._stash_access_locked():
                error = self._stash_error or "ACCOUNT_STASH_OUT_OF_REACH"
            elif len([
                row for row in self._item_instances.values()
                if isinstance(row, dict) and str(row.get("location")) == "INVENTORY"
                and str(row.get("owner_id")) == "player"
            ]) >= item_state.MAX_INVENTORY_SLOTS:
                error = "ITEM_INVENTORY_FULL"
            elif len(self._item_instances) >= item_state.MAX_WORLD_INSTANCES:
                error = "ITEM_WORLD_CAPACITY_REACHED"
            wanted = str(instance_id or "")
            current = next((row for row in self._stash_state.get("items", [])
                            if isinstance(row, dict) and row.get("instance_id") == wanted), None)
            if not error and current is None:
                error = "ACCOUNT_STASH_ITEM_MISSING"
            candidate = item_state.normalize_instance(self._item_catalog, current) if current else None
            if not error and (candidate is None or wanted in self._item_instances):
                error = "ACCOUNT_STASH_ITEM_INVALID"
            if not error and candidate.get('bound_to') and candidate['bound_to']!=str(self._persistence_key):
                error = 'ITEM_BOUND_TO_ANOTHER_CHARACTER'
            if error:
                snapshot = self.snapshot_locked()
                snapshot["error"] = error
                return snapshot
            try:
                result = self._stash_store.withdraw(self._account_id, wanted)
            except (OSError, ValueError) as exc:
                self._stash_error = type(exc).__name__ + ":" + str(exc)
                result = {"error": self._stash_error}
            if result.get("error"):
                self._stash_state = result
                snapshot = self.snapshot_locked()
                snapshot["error"] = result["error"]
                return snapshot
            candidate = item_state.normalize_instance(self._item_catalog, result.get("item"))
            if candidate is None:
                snapshot = self.snapshot_locked()
                snapshot["error"] = "ACCOUNT_STASH_ITEM_INVALID"
                return snapshot
            self._stash_state = result
            self._move_item_locked(candidate, "INVENTORY", owner_id="player")
            target = _safe_int(slot_index, -1)
            if 0 <= target < item_state.MAX_INVENTORY_SLOTS:
                self._ensure_inventory_slots_locked()
                used = {
                    int(row.get("slot_index", -1))
                    for row in self._item_instances.values()
                    if isinstance(row, dict) and str(row.get("location")) == "INVENTORY"
                    and str(row.get("owner_id")) == "player"
                }
                for row in self._item_instances.values():
                    if isinstance(row, dict) and str(row.get("location")) == "INVENTORY" and str(row.get("owner_id")) == "player" and int(row.get("slot_index", -1)) == target:
                        row["slot_index"] = next(
                            index for index in range(item_state.MAX_INVENTORY_SLOTS)
                            if index not in used
                        )
                        break
                candidate["slot_index"] = target
            self._item_instances[wanted] = candidate
            self._last_item_interaction = {"action": "BANK_WITHDRAW", "name": candidate.get("name", "")}
            self._append_event_locked("BANK_WITHDRAW", f"Took {candidate.get('name', 'item')} from the shared chest.")
            self._sync_saved_player_items_locked()
            snapshot = self.snapshot_locked()
            snapshot["item_result"] = dict(self._last_item_interaction)
            return snapshot

    def move_stash_slot(self, instance_id: str, slot_index: int) -> dict[str, Any]:
        with self._lock:
            if not self._stash_access_locked():
                snapshot = self.snapshot_locked()
                snapshot["error"] = self._stash_error or "ACCOUNT_STASH_OUT_OF_REACH"
                return snapshot
            try:
                result = self._stash_store.move(self._account_id, str(instance_id or ""), _safe_int(slot_index, -1))
            except (OSError, ValueError) as exc:
                self._stash_error = type(exc).__name__ + ":" + str(exc)
                result = {"error": self._stash_error}
            if isinstance(result.get("items"), list):
                self._stash_state = result
            snapshot = self.snapshot_locked()
            if result.get("error"):
                snapshot["error"] = result["error"]
            else:
                snapshot["item_result"] = {"action": "BANK_MOVE"}
            return snapshot

    def grant_experience(self, amount: int = 25) -> dict[str, Any]:
        with self._lock:
            result = progression.grant_xp(self._progression, amount)
            self._append_event_locked(
                "XP",
                f"Gained {result['xp_gained']} XP; level {result['level']}.",
            )
            snapshot = self.snapshot_locked()
            snapshot["xp_result"] = result
            return snapshot

    def add_talent(self, talent_id: str = "trailblazer") -> dict[str, Any]:
        with self._lock:
            ok, result = progression.add_talent(self._progression, talent_id)
            snapshot = self.snapshot_locked()
            if not ok:
                snapshot["error"] = result.get("error", "TALENT_FAILED")
            else:
                self._append_event_locked("TALENT", f"Talent {talent_id} improved.")
            snapshot["talent_result"] = result
            return snapshot

    def select_race(self, race: str = "ISLANDER") -> dict[str, Any]:
        with self._lock:
            ok, result = progression.select_race(self._progression, race)
            snapshot = self.snapshot_locked()
            if not ok:
                snapshot["error"] = result.get("error", "RACE_FAILED")
            else:
                self._append_event_locked("RACE", f"Race selected: {result['race'].lower()}.")
            snapshot["race_result"] = result
            return snapshot

    def select_spec(self, spec: str = "EXPLORER") -> dict[str, Any]:
        with self._lock:
            ok, result = progression.select_spec(self._progression, spec)
            snapshot = self.snapshot_locked()
            if not ok:
                snapshot["error"] = result.get("error", "SPEC_FAILED")
            else:
                self._append_event_locked("SPEC", f"Spec selected: {result['spec'].lower()}.")
            snapshot["spec_result"] = result
            return snapshot

    def editor_place(self, kind: str = "PROP") -> dict[str, Any]:
        with self._lock:
            normalized_kind = str(kind or "PROP").upper()
            facing = controller.character_basis(self._yaw[0])
            forward_x, forward_z = facing["forward"]
            distance = 4.0
            placement_x = self._x[0] + forward_x * distance
            placement_z = self._z[0] + forward_z * distance
            y = self._y[0] if self._movement_mode != "GROUND" else 0.8
            scale = {
                "RAMP": (1.5, 1.2, 2.2),
                "LIGHT": (0.35, 1.5, 0.35),
                "SPAWN": (0.55, 0.55, 0.55),
                "NPC": (0.9, 1.1, 0.9),
            }.get(normalized_kind, (0.8, 0.9, 0.8))
            color = {
                "RAMP": "#6aa8c8",
                "LIGHT": "#c8a97e",
                "SPAWN": "#b6a6c8",
                "NPC": "#d7a36f",
            }.get(normalized_kind, "#8fa8a0")
            if normalized_kind == "NPC" and self._movement_mode == "GROUND":
                y = self._terrain_height_locked(placement_x, placement_z) + 0.65
            ok, result = editor_contract.place(
                self._editor_document,
                kind,
                (
                    placement_x,
                    y,
                    placement_z,
                ),
                scale,
                color,
            )
            if not ok:
                snapshot = self.snapshot_locked()
                snapshot["error"] = result.get("error", "EDITOR_PLACE_FAILED")
                snapshot["editor_result"] = result
                return snapshot
            placement = result["placement"]
            if placement["kind"] == "NPC":
                slot = self._spawn_npc_locked(
                    {
                        "id": f"editor-{placement['id']}",
                        "archetype": "WANDERER",
                        "x": placement["x"],
                        "z": placement["z"],
                        "scale": (
                            placement["sx"],
                            placement["sy"],
                            placement["sz"],
                        ),
                        "color": placement["color"],
                        "phase": float(self._editor_document.get("revision", 0)) * 0.73,
                    }
                )
            else:
                slot = self._spawn_entity_locked(
                    f"EDITOR_{placement['kind']}",
                    placement["x"],
                    placement["y"],
                    placement["z"],
                    (placement["sx"], placement["sy"], placement["sz"]),
                    placement["color"],
                    0.8,
                )
            if slot is None:
                editor_contract.undo(self._editor_document)
                snapshot = self.snapshot_locked()
                snapshot["error"] = "EDITOR_ENTITY_POOL_FULL"
                return snapshot
            editor_contract.attach_entity(
                self._editor_document,
                placement["id"],
                f"e-{slot:04d}",
            )
            self._editor_entity_indices[placement["id"]] = slot
            self._append_event_locked(
                "EDITOR_PLACE",
                f"Placed {placement['kind'].lower()} in the live scene.",
            )
            snapshot = self.snapshot_locked()
            snapshot["editor_result"] = {"placement": placement}
            return snapshot

    def editor_undo(self) -> dict[str, Any]:
        with self._lock:
            ok, result = editor_contract.undo(self._editor_document)
            if not ok:
                snapshot = self.snapshot_locked()
                snapshot["error"] = result.get("error", "EDITOR_UNDO_FAILED")
                snapshot["editor_result"] = result
                return snapshot
            placement = result["placement"]
            slot = self._editor_entity_indices.pop(str(placement.get("id")), None)
            if slot is not None:
                self._despawn_entity_locked(slot)
            self._append_event_locked(
                "EDITOR_UNDO",
                f"Removed {placement.get('kind', 'object').lower()}.",
            )
            snapshot = self.snapshot_locked()
            snapshot["editor_result"] = result
            return snapshot

    def _regional_interaction_target_locked(self,npc_id=''):
        if self._instance_private_locked():return None
        """Talk targets use the same saved clock and identity as the renderer."""
        wanted=str(npc_id or '');candidates=[]
        for identity in self._world_population.active:
            if wanted and identity!=wanted:continue
            person=self._world_population.people[identity]
            if not person['alive']:continue
            p=self._world_population.position(identity,self._sim_time)
            distance=math.hypot(p['x']-self._x[0],p['z']-self._z[0])
            if distance>npc_contract.INTERACTION_RADIUS_M:continue
            ground=self._terrain_height_locked(p['x'],p['z'])+.65
            if abs(self._y[0]-ground)>3:continue
            # Check actual house walls along this short talk segment. The
            # open doorway is allowed; a conversation through a wall is not.
            blocked=False
            for step in range(1,max(2,math.ceil(distance/.2))):
                fraction=step/max(2,math.ceil(distance/.2))
                x=self._x[0]+(p['x']-self._x[0])*fraction;z=self._z[0]+(p['z']-self._z[0])*fraction
                wx,wz=world_places_contract.building_walls(x,z,ground,self._terrain_height_locked)
                if math.hypot(wx-x,wz-z)>.001:blocked=True;break
            if not blocked:candidates.append((distance,identity))
        if not candidates:return None
        distance,identity=min(candidates)
        return dict(id=identity,entity_id=identity,name=self._world_population.people[identity]['name'],archetype='WANDERER',state='WANDER',distance_m=round(distance,3))

    def _regional_dialogue_catalog_locked(self,identity=''):
        selected=identity or self._dialogue_state.get('active',{}).get('npc_id','')
        if selected not in self._world_population.people:return self._dialogue_catalog
        return {**self._dialogue_catalog,selected:self._world_population.dialogue_tree(selected)}

    def _talk_regional_locked(self,identity,choice_id=''):
        target=self._regional_interaction_target_locked(identity)
        if not target:
            snapshot=self.snapshot_locked();snapshot['error']='NPC_DIALOGUE_OUT_OF_RANGE'
            snapshot['dialogue_result']=dict(error=snapshot['error'],npc_id=identity)
            return snapshot
        definitions=self._regional_dialogue_catalog_locked(identity)
        function=dialogue_contract.choose if choice_id else dialogue_contract.start
        args=(self._dialogue_state,definitions,identity,choice_id,self._sim_time) if choice_id else (self._dialogue_state,definitions,identity,self._sim_time)
        previous_identity=self._dialogue_state.get('active',{}).get('npc_id','')
        ok,result=function(*args)
        if ok:
            if previous_identity!=identity and previous_identity in self._world_population.people:
                self._world_population.resume_route(previous_identity,self._sim_time)
            if result.get('node',{}).get('choices'):self._world_population.pause_for_talk(identity,self._sim_time)
            else:self._world_population.resume_route(identity,self._sim_time)
            person=self._world_population.people[identity]
            person['interaction_count']=person.get('interaction_count',0)+1
            self._world_population.remember(identity,'TALKED_TO_PLAYER_'+(choice_id or 'GREETING').upper(),self._sim_time)
            self._npc_last_interaction={**target,'interaction_count':person['interaction_count'],'dialogue':copy.deepcopy(result)}
            self._append_event_locked('DIALOGUE_CHOICE' if choice_id else 'DIALOGUE_START',
                'Conversation with '+person['name']+'.',actor_id='player',target_id=identity,payload=copy.deepcopy(result))
        snapshot=self.snapshot_locked();snapshot['dialogue_result']=result
        if not ok:snapshot['error']=result.get('error','DIALOGUE_CHOICE_FAILED')
        return snapshot

    def close_dialogue(self):
        with self._lock:
            self._engine_quest_panel={};self._engine_gossip_hidden=False
            identity=self._dialogue_state.get('active',{}).get('npc_id','')
            if identity in self._world_population.people:self._world_population.resume_route(identity,self._sim_time)
            self._dialogue_state['active']=dict(npc_id='',tree_id='',node_id='',turn=0)
            self._dialogue_state['revision']=self._dialogue_state.get('revision',0)+1
            return self.snapshot_locked()

    def _conversation_target_locked(
        self,
        npc_id: str = "",
    ) -> tuple[int | None, float, str | None]:
        """Resolve a live physical NPC for interaction/dialogue.

        Ambient proxies can be observed by the population layer, but they are
        deliberately not conversation targets until promoted into the real
        NPC pool.  This keeps dialogue, LOS and future trade/combat effects on
        one authoritative actor identity.
        """
        wanted = str(npc_id or "").strip()
        radius = npc_contract.INTERACTION_RADIUS_M
        candidates: list[tuple[float, str, int]] = []
        for index in self._npc_indices:
            if not self._alive[index] or not self._npc_ids[index]:
                continue
            identity = str(self._npc_ids[index])
            if wanted and identity != wanted:
                continue
            actor = self._combat_state.get("actors", {}).get(identity)
            if isinstance(actor, dict) and not actor.get("alive", True):
                continue
            distance = math.hypot(
                self._x[index] - self._x[0],
                self._z[index] - self._z[0],
            )
            if not wanted and distance > radius:
                continue
            candidates.append((distance, identity, index))
        candidates.sort(key=lambda row: (row[0], row[1]))
        if not candidates:
            return None, 0.0, "NPC_INTERACTION_TARGET_REQUIRED"
        distance, _, index = candidates[0]
        if distance > radius:
            return index, distance, "NPC_DIALOGUE_OUT_OF_RANGE"
        if not self._npc_line_of_sight_locked(index):
            return index, distance, "NPC_INTERACTION_OCCLUDED"
        return index, distance, None

    def _apply_dialogue_effects_locked(
        self,
        npc_id: str,
        dialogue_result: dict[str, Any],
    ) -> tuple[bool, dict[str, Any]]:
        """Apply authored choice effects to the real quest/person stores."""
        effects = dialogue_result.get("effects", [])
        if not isinstance(effects, list):
            effects = []
        applied: list[dict[str, Any]] = []
        quest_results: list[dict[str, Any]] = []
        quest_events: list[dict[str, Any]] = []
        relationship_results: list[dict[str, Any]] = []
        for raw_effect in effects[: dialogue_contract.MAX_CHOICES]:
            if not isinstance(raw_effect, dict):
                continue
            kind = str(raw_effect.get("kind", "")).upper()
            if kind == "ACCEPT_QUEST":
                quest_id = str(raw_effect.get("quest_id", ""))
                ok, result = quests_contract.accept(
                    self._quest_state,
                    self._quest_catalog,
                    quest_id,
                    self._sim_time,
                )
                if not ok:
                    return False, {
                        "error": result.get("error", "DIALOGUE_QUEST_EFFECT_FAILED"),
                        "quest_id": quest_id,
                        "effect": copy.deepcopy(raw_effect),
                        "details": copy.deepcopy(result),
                    }
                quest_results.append(copy.deepcopy(result))
                identity_contract.record_memory(
                    self._individual_state,
                    npc_id,
                    "QUEST_GIVEN",
                    "player",
                    self._sim_time,
                    text=f"Gave quest {quest_id} to the player during a real conversation.",
                    weight=0.76,
                )
                applied.append({"kind": kind, "quest_id": quest_id, "ok": True})
                continue
            if kind == "RELATIONSHIP":
                people = self._individual_state.get("individuals", {})
                person = people.get(npc_id) if isinstance(people, dict) else None
                if not isinstance(person, dict):
                    return False, {
                        "error": "DIALOGUE_IDENTITY_NOT_FOUND",
                        "npc_id": npc_id,
                    }
                amount = _clamp(raw_effect.get("amount"), -1.0, 1.0)
                before = _clamp(person.get("relationship_to_player"), -1.0, 1.0)
                after = _clamp(before + amount, -1.0, 1.0)
                person["relationship_to_player"] = round(after, 4)
                person["revision"] = max(0, _safe_int(person.get("revision"))) + 1
                relationship_results.append(
                    {
                        "npc_id": npc_id,
                        "before": round(before, 4),
                        "after": round(after, 4),
                        "delta": round(after - before, 4),
                    }
                )
                applied.append(
                    {
                        "kind": kind,
                        "amount": round(after - before, 4),
                        "npc_id": npc_id,
                    }
                )
                continue
            if kind == "FACTION":
                faction_id = str(raw_effect.get("faction_id", "")).upper()
                if not faction_id:
                    return False, {"error": "DIALOGUE_FACTION_ID_REQUIRED"}
                faction_result = factions_contract.adjust_player(
                    self._faction_state,
                    faction_id,
                    int(round(_clamp(raw_effect.get("amount"), -1.0, 1.0) * 100.0)),
                    source="DIALOGUE",
                    sim_time=self._sim_time,
                )
                applied.append(
                    {
                        "kind": kind,
                        "faction_id": faction_id,
                        "result": copy.deepcopy(faction_result),
                    }
                )
                continue
            if kind == "QUEST_EVENT":
                event = {
                    "kind": str(raw_effect.get("event_kind", "TALK")).upper(),
                    "target_id": npc_id,
                    "choice_id": str(
                        raw_effect.get("choice_id")
                        or dialogue_result.get("choice_id", "")
                    ),
                    "amount": 1,
                }
                quest_result = self._record_quest_event_locked(event)
                quest_events.append({"event": event, "result": copy.deepcopy(quest_result)})
                applied.append({"kind": kind, "event": event, "result": quest_result})
                continue
            return False, {
                "error": "DIALOGUE_EFFECT_UNSUPPORTED",
                "kind": kind,
            }

        # Every authored choice is also a real TALK event unless its content
        # explicitly supplied one.  This lets future quest tables bind to any
        # conversation without making the renderer aware of quest semantics.
        if not quest_events and dialogue_result.get("choice_id"):
            event = {
                "kind": "TALK",
                "target_id": npc_id,
                "choice_id": str(dialogue_result.get("choice_id", "")),
                "amount": 1,
            }
            quest_result = self._record_quest_event_locked(event)
            quest_events.append({"event": event, "result": copy.deepcopy(quest_result)})

        return True, {
            "effects_applied": applied,
            "quests": quest_results,
            "quest_events": quest_events,
            "relationships": relationship_results,
        }

    def talk_npc(
        self,
        npc_id: str = "",
        choice_id: str = "",
    ) -> dict[str, Any]:
        """Start or continue a real nearby NPC conversation."""
        with self._lock:
            if not choice_id:self._engine_quest_panel={};self._engine_gossip_hidden=False
            if npc_id in self._world_population.people:
                return self._talk_regional_locked(npc_id,str(choice_id or ''))
            regional=self._regional_interaction_target_locked() if not npc_id else None
            index, distance, target_error = self._conversation_target_locked(npc_id)
            if regional and (index is None or target_error or regional['distance_m']<distance):
                return self._talk_regional_locked(regional['id'],str(choice_id or ''))
            if index is None or target_error:
                result = {
                    "error": target_error or "NPC_INTERACTION_TARGET_REQUIRED",
                    "npc_id": str(npc_id or ""),
                    "distance_m": round(distance, 3),
                    "radius_m": npc_contract.INTERACTION_RADIUS_M,
                }
                snapshot = self.snapshot_locked()
                snapshot["error"] = result["error"]
                snapshot["dialogue_result"] = result
                return snapshot
            resolved_id = str(self._npc_ids[index])
            if str(choice_id or "").strip():
                before_dialogue = copy.deepcopy(self._dialogue_state)
                before_quests = copy.deepcopy(self._quest_state)
                before_factions = copy.deepcopy(self._faction_state)
                before_people = copy.deepcopy(self._individual_state)
                ok, result = dialogue_contract.choose(
                    self._dialogue_state,
                    self._dialogue_catalog,
                    resolved_id,
                    str(choice_id),
                    self._sim_time,
                )
                if ok:
                    ok, effects = self._apply_dialogue_effects_locked(
                        resolved_id,
                        result,
                    )
                    if not ok:
                        self._dialogue_state = before_dialogue
                        self._quest_state = before_quests
                        self._faction_state = before_factions
                        self._individual_state = before_people
                        result = effects
                    else:
                        result["effects_result"] = effects
                if not ok:
                    snapshot = self.snapshot_locked()
                    snapshot["error"] = result.get("error", "DIALOGUE_CHOICE_FAILED")
                    snapshot["dialogue_result"] = result
                    return snapshot
                identity_contract.record_memory(
                    self._individual_state,
                    resolved_id,
                    "DIALOGUE",
                    "player",
                    self._sim_time,
                    text=f"Answered {result.get('choice_id', '')} in a real conversation.",
                    weight=0.68,
                )
                self._append_event_locked(
                    "DIALOGUE_CHOICE",
                    f"Player chose {result.get('choice_id', '')} with {resolved_id}.",
                    actor_id="player",
                    subject_id=str(result.get("choice_id", "")),
                    target_id=resolved_id,
                    payload=copy.deepcopy(result),
                )
            else:
                ok, result = dialogue_contract.start(
                    self._dialogue_state,
                    self._dialogue_catalog,
                    resolved_id,
                    self._sim_time,
                )
                if not ok:
                    snapshot = self.snapshot_locked()
                    snapshot["error"] = result.get("error", "DIALOGUE_START_FAILED")
                    snapshot["dialogue_result"] = result
                    return snapshot
                self._append_event_locked(
                    "DIALOGUE_START",
                    f"Conversation opened with {resolved_id}.",
                    actor_id="player",
                    target_id=resolved_id,
                    payload=copy.deepcopy(result),
                )
            self._npc_interaction_count[index] += 1
            self._npc_last_interaction = {
                "id": resolved_id,
                "entity_id": f"e-{index:04d}",
                "archetype": self._npc_archetype[index],
                "state": self._npc_state[index],
                "distance_m": round(distance, 3),
                "interaction_count": self._npc_interaction_count[index],
                "response": npc_contract.interaction_response(
                    self._npc_archetype[index],
                    self._npc_state[index],
                ),
                "dialogue": copy.deepcopy(result),
            }
            snapshot = self.snapshot_locked()
            snapshot["dialogue_result"] = result
            return snapshot

    def npc_interact(self) -> dict[str, Any]:
        """Interact with the nearest NPC and open its authored conversation."""
        with self._lock:
            best_index, best_distance, target_error = self._conversation_target_locked()
            regional=self._regional_interaction_target_locked()
            if regional and (best_index is None or target_error or regional['distance_m']<best_distance):
                snapshot=self._talk_regional_locked(regional['id'])
                snapshot['npc_interaction_result']=copy.deepcopy(self._npc_last_interaction)
                return snapshot
            radius = npc_contract.INTERACTION_RADIUS_M
            if best_index is None:
                snapshot = self.snapshot_locked()
                result = {"error": target_error or "NPC_INTERACTION_TARGET_REQUIRED", "radius_m": radius}
                snapshot["error"] = result["error"]
                snapshot["npc_interaction_result"] = result
                return snapshot
            if target_error:
                snapshot = self.snapshot_locked()
                result = {
                    "error": target_error,
                    "id": self._npc_ids[best_index],
                    "radius_m": radius,
                }
                snapshot["error"] = result["error"]
                snapshot["npc_interaction_result"] = result
                return snapshot
            self._npc_interaction_count[best_index] += 1
            identity_id = str(self._npc_ids[best_index])
            result = {
                "id": identity_id,
                "entity_id": f"e-{best_index:04d}",
                "archetype": self._npc_archetype[best_index],
                "state": self._npc_state[best_index],
                "distance_m": round(best_distance, 3),
                "interaction_count": self._npc_interaction_count[best_index],
                "response": npc_contract.interaction_response(
                    self._npc_archetype[best_index],
                    self._npc_state[best_index],
                ),
            }
            dialogue_ok, dialogue_result = dialogue_contract.start(
                self._dialogue_state,
                self._dialogue_catalog,
                identity_id,
                self._sim_time,
            )
            if dialogue_ok:
                result["dialogue"] = dialogue_result
                identity_contract.record_memory(
                    self._individual_state,
                    identity_id,
                    "DIALOGUE",
                    "player",
                    self._sim_time,
                    text="The player opened a real conversation with me.",
                    weight=0.62,
                )
                self._append_event_locked(
                    "DIALOGUE_START",
                    f"Conversation opened with {identity_id}.",
                    actor_id="player",
                    target_id=identity_id,
                    payload=copy.deepcopy(dialogue_result),
                )
            self._npc_last_interaction = dict(result)
            self._append_event_locked(
                "NPC_INTERACT",
                f"Interacted with {identity_id}.",
                actor_id="player",
                target_id=identity_id,
                payload={
                    "entity_id": f"e-{best_index:04d}",
                    "archetype": self._npc_archetype[best_index],
                    "state": self._npc_state[best_index],
                    "interaction_count": self._npc_interaction_count[best_index],
                    "dialogue": copy.deepcopy(dialogue_result) if dialogue_ok else {},
                },
            )
            snapshot = self.snapshot_locked()
            snapshot["npc_interaction_result"] = result
            return snapshot

    def trade_items(
        self,
        npc_id: str = "",
        give_instance_id: str = "",
        receive_instance_id: str = "",
    ) -> dict[str, Any]:
        """Atomically exchange one player item instance with a nearby NPC."""
        request = trade_contract.normalize_request(
            npc_id,
            give_instance_id,
            receive_instance_id,
        )

        with self._lock:
            def failure(error: str, **details: Any) -> dict[str, Any]:
                result = {
                    "schema": trade_contract.SCHEMA,
                    "version": trade_contract.VERSION,
                    "error": str(error),
                    **details,
                }
                snapshot = self.snapshot_locked()
                snapshot["error"] = str(error)
                snapshot["trade_result"] = result
                return snapshot

            requested_npc_id = str(request.get("npc_id", ""))
            give_id = str(request.get("give_instance_id", ""))
            receive_id = str(request.get("receive_instance_id", ""))
            if not give_id or not receive_id:
                return failure(
                    "TRADE_INSTANCE_IDS_REQUIRED",
                    request=request,
                )
            if give_id == receive_id:
                return failure(
                    "TRADE_INSTANCE_IDS_MUST_DIFFER",
                    request=request,
                )

            best_index: int | None = None
            best_distance = float("inf")
            radius = npc_contract.INTERACTION_RADIUS_M
            for index in self._npc_indices:
                if not self._alive[index]:
                    continue
                identity_id = str(self._npc_ids[index])
                if requested_npc_id and identity_id != requested_npc_id:
                    continue
                distance = math.hypot(
                    self._x[index] - self._x[0],
                    self._z[index] - self._z[0],
                )
                if distance > radius:
                    continue
                if distance > best_distance or (
                    abs(distance - best_distance) <= 0.0001
                    and best_index is not None
                    and identity_id >= str(self._npc_ids[best_index])
                ):
                    continue
                best_index = index
                best_distance = distance
            if best_index is None:
                return failure(
                    "NPC_TRADE_TARGET_REQUIRED"
                    if not requested_npc_id
                    else "NPC_TRADE_NPC_UNAVAILABLE",
                    npc_id=requested_npc_id,
                    radius_m=radius,
                )
            if not self._npc_line_of_sight_locked(best_index):
                return failure(
                    "NPC_TRADE_OCCLUDED",
                    npc_id=str(self._npc_ids[best_index]),
                    radius_m=radius,
                )

            identity_id = str(self._npc_ids[best_index])
            people = self._individual_state.get("individuals", {})
            person = people.get(identity_id) if isinstance(people, dict) else None
            if not isinstance(person, dict):
                return failure(
                    "NPC_TRADE_IDENTITY_MISSING",
                    npc_id=identity_id,
                )
            inventory_refs = person.get("inventory")
            if not isinstance(inventory_refs, list):
                return failure(
                    "NPC_TRADE_INVENTORY_MISSING",
                    npc_id=identity_id,
                )

            player_item = self._item_instance_locked(give_id)
            npc_item = self._item_instance_locked(receive_id)
            player_definition = item_state.definition(
                self._item_catalog,
                player_item.get("definition_id") if isinstance(player_item, dict) else "",
            )
            npc_definition = item_state.definition(
                self._item_catalog,
                npc_item.get("definition_id") if isinstance(npc_item, dict) else "",
            )
            ok, player_offer = trade_contract.validate_offer(
                player_item,
                player_definition,
                owner_id="player",
                location=trade_contract.PLAYER_SOURCE_LOCATION,
            )
            if not ok:
                return failure(
                    str(player_offer.get("error", "TRADE_PLAYER_OFFER_INVALID")),
                    offer="PLAYER",
                    instance_id=give_id,
                    details=player_offer,
                )
            ok, npc_offer = trade_contract.validate_offer(
                npc_item,
                npc_definition,
                owner_id=identity_id,
                location=trade_contract.NPC_SOURCE_LOCATION,
            )
            if not ok:
                return failure(
                    str(npc_offer.get("error", "TRADE_NPC_OFFER_INVALID")),
                    offer="NPC",
                    instance_id=receive_id,
                    details=npc_offer,
                )

            player_definition_id = str(player_item.get("definition_id", ""))
            npc_definition_id = str(npc_item.get("definition_id", ""))
            if npc_definition_id not in {str(value) for value in inventory_refs}:
                return failure(
                    "TRADE_NPC_REFERENCE_MISSING",
                    npc_id=identity_id,
                    instance_id=receive_id,
                    definition_id=npc_definition_id,
                )
            player_quantity = max(1, int(player_item.get("quantity", 1)))
            if int(self._inventory.get(player_definition_id, 0)) < player_quantity:
                return failure(
                    "TRADE_PLAYER_INVENTORY_DESYNC",
                    instance_id=give_id,
                    definition_id=player_definition_id,
                )

            # Both sides exchange one complete instance.  Backing up only the
            # two rows, the legacy player count and this person's durable row
            # makes rollback bounded while retaining the canonical move path.
            player_backup = copy.deepcopy(player_item)
            npc_backup = copy.deepcopy(npc_item)
            inventory_backup = dict(self._inventory)
            person_backup = copy.deepcopy(person)
            interaction_count_backup = self._npc_interaction_count[best_index]
            npc_gear_decision: dict[str, Any] = {}
            npc_power_result: dict[str, Any] = {}
            try:
                ok, transition = self._move_item_locked(
                    player_item,
                    trade_contract.NPC_SOURCE_LOCATION,
                    owner_id=identity_id,
                )
                if not ok:
                    raise ValueError(str(transition.get("error", "TRADE_PLAYER_MOVE_FAILED")))
                ok, transition = self._move_item_locked(
                    npc_item,
                    trade_contract.PLAYER_SOURCE_LOCATION,
                    owner_id="player",
                )
                if not ok:
                    raise ValueError(str(transition.get("error", "TRADE_NPC_MOVE_FAILED")))
                if not self._npc_remove_inventory_ref_locked(person, npc_definition_id):
                    raise ValueError("TRADE_NPC_REFERENCE_REMOVE_FAILED")
                if not self._npc_add_inventory_ref_locked(person, player_definition_id):
                    raise ValueError("TRADE_NPC_INVENTORY_FULL")
                self._npc_interaction_count[best_index] += 1
                identity_contract.record_memory(
                    self._individual_state,
                    identity_id,
                    "TRADE",
                    "player",
                    self._sim_time,
                    text=(
                        f"Traded {str(player_item.get('name', player_definition_id))} "
                        f"for {str(npc_item.get('name', npc_definition_id))}."
                    ),
                    weight=0.72,
                )
                upgraded, npc_gear_decision = self._npc_equip_better_gear_locked(
                    identity_id,
                    person,
                    player_item,
                )
                if upgraded:
                    npc_gear_decision["gear_upgrade"] = True
                npc_power_result = self._refresh_npc_progression_locked(
                    identity_id,
                    person,
                    source="TRADE",
                )
            except (TypeError, ValueError) as exc:
                self._item_instances[give_id] = player_backup
                self._item_instances[receive_id] = npc_backup
                self._inventory = inventory_backup
                person.clear()
                person.update(person_backup)
                self._npc_interaction_count[best_index] = interaction_count_backup
                return failure(
                    "TRADE_ATOMIC_ROLLBACK",
                    npc_id=identity_id,
                    cause=str(exc)[:96],
                )

            result = trade_contract.normalize_result(
                {
                    "action": "TRADE",
                    "npc_id": identity_id,
                    "distance_m": best_distance,
                    "policy": "ITEM_FOR_ITEM_WHOLE_INSTANCE",
                    "give": item_state.instance_view(
                        self._item_catalog,
                        player_item,
                        sim_time=self._sim_time,
                    ),
                    "receive": item_state.instance_view(
                        self._item_catalog,
                        npc_item,
                        sim_time=self._sim_time,
                    ),
                    "player_gave": item_state.instance_view(
                        self._item_catalog,
                        player_item,
                        sim_time=self._sim_time,
                    ),
                    "player_received": item_state.instance_view(
                        self._item_catalog,
                        npc_item,
                        sim_time=self._sim_time,
                    ),
                    "interaction_count": self._npc_interaction_count[best_index],
                    "npc_gear_upgrade": npc_gear_decision,
                    "npc_power": npc_power_result,
                }
            )
            self._last_trade = result
            self._last_item_interaction = result
            self._npc_last_interaction = {
                "id": identity_id,
                "entity_id": f"e-{best_index:04d}",
                "archetype": self._npc_archetype[best_index],
                "state": self._npc_state[best_index],
                "distance_m": round(best_distance, 3),
                "interaction_count": self._npc_interaction_count[best_index],
                "response": "A real item exchange was completed.",
            }
            self._append_event_locked(
                "NPC_TRADE",
                f"Traded with {identity_id} using real item instances.",
                actor_id="player",
                subject_id=give_id,
                target_id=identity_id,
                payload={
                    "give_instance_id": give_id,
                    "give_definition_id": player_definition_id,
                    "give_quantity": player_quantity,
                    "receive_instance_id": receive_id,
                    "receive_definition_id": npc_definition_id,
                    "receive_quantity": max(1, int(npc_item.get("quantity", 1))),
                    "distance_m": round(best_distance, 3),
                    "interaction_count": self._npc_interaction_count[best_index],
                    "npc_gear_upgrade": copy.deepcopy(npc_gear_decision),
                    "npc_power": copy.deepcopy(npc_power_result),
                    "atomic": True,
                },
            )
            if npc_power_result.get("changed"):
                progression_state = person.get("progression", {})
                self._append_event_locked(
                    "NPC_POWER_CHANGED",
                    f"{identity_id} power is now {npc_power_result.get('power_score', 0)} "
                    f"(gear {npc_power_result.get('gear_score', 0)}).",
                    actor_id="player",
                    subject_id="POWER",
                    target_id=identity_id,
                    payload={
                        "source": "TRADE",
                        "power": copy.deepcopy(npc_power_result),
                        "progression": npc_progression.summary(progression_state),
                    },
                )
            snapshot = self.snapshot_locked()
            snapshot["trade_result"] = copy.deepcopy(result)
            return snapshot

    def _vendor_target_locked(
        self,
        requested_vendor_id: str = "",
    ) -> tuple[bool, dict[str, Any]]:
        """Resolve a configured vendor against a live nearby NPC."""
        if not self._combat_state.get('actors', {}).get('player', {}).get('alive', True):
            return False, {"error": "PLAYER_DEFEATED"}
        wanted = str(requested_vendor_id or "").strip()
        resolved = (
            economy_contract.vendor_for(self._vendor_catalog, wanted)
            if wanted
            else None
        )
        if wanted and resolved is None:
            return False, {"error": "VENDOR_NOT_FOUND", "vendor_id": wanted}
        requested_id = resolved[0] if resolved is not None else ""
        best: dict[str, Any] | None = None
        radius = economy_contract.INTERACTION_RADIUS_M
        for vendor_id in sorted(self._vendor_catalog):
            if requested_id and vendor_id != requested_id:
                continue
            vendor = self._vendor_catalog.get(vendor_id)
            if not isinstance(vendor, dict):
                continue
            npc_id = str(vendor.get("npc_id", ""))
            for index in self._npc_indices:
                if not self._alive[index] or str(self._npc_ids[index]) != npc_id:
                    continue
                if not self._combat_state.get('actors', {}).get(npc_id, {}).get('alive', True):
                    continue
                distance = math.hypot(
                    self._x[index] - self._x[0],
                    self._z[index] - self._z[0],
                )
                if distance > radius:
                    continue
                candidate = {
                    "vendor_id": str(vendor_id),
                    "vendor": vendor,
                    "npc_id": npc_id,
                    "index": index,
                    "distance_m": distance,
                }
                if best is None or distance < best["distance_m"] or (
                    abs(distance - best["distance_m"]) <= 0.0001
                    and str(vendor_id) < str(best["vendor_id"])
                ):
                    best = candidate
                break
        if best is None:
            return False, {
                "error": "VENDOR_NPC_UNAVAILABLE"
                if wanted
                else "VENDOR_TARGET_REQUIRED",
                "vendor_id": requested_id or wanted,
                "radius_m": radius,
            }
        if not self._npc_line_of_sight_locked(int(best["index"])):
            return False, {
                "error": "VENDOR_OCCLUDED",
                "vendor_id": str(best["vendor_id"]),
                "npc_id": str(best["npc_id"]),
                "radius_m": radius,
            }
        return True, best

    def _vendor_transaction_locked(
        self,
        action: str,
        vendor_id: str = "",
        instance_id: str = "",
        *, destination_slot: int | None = None,
        reserve_buyback: bool = False,
        buyback_price: int | None = None,
    ) -> dict[str, Any]:
        """Commit the canonical gold, stock and custody change together."""
        return self._vendor_durable_locked(lambda:self._vendor_transition_locked(
            action,vendor_id,instance_id,destination_slot=destination_slot,
            reserve_buyback=reserve_buyback,buyback_price=buyback_price))

    def _vendor_transition_locked(
        self,action: str,vendor_id: str = "",instance_id: str = "",*,
        destination_slot: int | None = None,reserve_buyback: bool = False,
        buyback_price: int | None = None,
        quote_override: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute one atomic gold/item transition against physical stock."""
        normalized_action = str(action or "").upper()

        def failure(error: str, **details: Any) -> dict[str, Any]:
            result = {
                "schema": economy_contract.SCHEMA,
                "version": economy_contract.VERSION,
                "ok": False,
                "action": normalized_action,
                "error": str(error),
                **details,
            }
            snapshot = self.snapshot_locked()
            snapshot["error"] = str(error)
            snapshot["economy_result"] = result
            return snapshot

        if normalized_action not in {"BUY", "SELL"}:
            return failure("VENDOR_ACTION_INVALID")
        wanted_instance_id = str(instance_id or "").strip()
        if not wanted_instance_id:
            return failure(
                "VENDOR_INSTANCE_REQUIRED",
                usage=f"{normalized_action} [vendor-id] instance-id",
            )

        ok, target = self._vendor_target_locked(vendor_id)
        if not ok:
            return failure(
                str(target.get("error", "VENDOR_TARGET_REQUIRED")),
                **{
                    key: value
                    for key, value in target.items()
                    if key != "error"
                },
            )
        resolved_vendor_id = str(target["vendor_id"])
        vendor = target["vendor"]
        identity_id = str(target["npc_id"])
        npc_index = int(target["index"])
        distance = float(target["distance_m"])
        accounts = self._economy_state.get("vendors", {})
        account = accounts.get(resolved_vendor_id) if isinstance(accounts, dict) else None
        if not isinstance(account, dict):
            return failure(
                "VENDOR_ACCOUNT_MISSING",
                vendor_id=resolved_vendor_id,
            )
        wallet = self._economy_state.get("wallet")
        if not isinstance(wallet, dict):
            return failure("PLAYER_WALLET_MISSING")
        people = self._individual_state.get("individuals", {})
        person = people.get(identity_id) if isinstance(people, dict) else None
        if not isinstance(person, dict):
            return failure("VENDOR_IDENTITY_MISSING", npc_id=identity_id)
        inventory_refs = person.get("inventory")
        if not isinstance(inventory_refs, list):
            return failure("VENDOR_INVENTORY_MISSING", npc_id=identity_id)

        instance = self._item_instance_locked(wanted_instance_id)
        definition_id = str(instance.get("definition_id", "")) if isinstance(instance, dict) else ""
        definition = item_state.definition(self._item_catalog, definition_id)
        if isinstance(instance, dict) and instance.get('bound_to') and instance['bound_to'] != str(self._persistence_key):
            return failure('ITEM_BOUND_TO_ANOTHER_CHARACTER', instance_id=wanted_instance_id)
        if not economy_contract.is_tradeable_definition(definition):
            return failure(
                "VENDOR_ITEM_NOT_TRADEABLE",
                instance_id=wanted_instance_id,
                definition_id=definition_id,
            )
        stock_count = self._vendor_stock_count_locked(vendor, definition_id)
        quote = (dict(quote_override) if quote_override is not None else economy_contract.dynamic_prices(
            vendor,account,definition_id,stock_count))
        if quote is None:
            return failure(
                "VENDOR_ITEM_NOT_PRICED",
                vendor_id=resolved_vendor_id,
                instance_id=wanted_instance_id,
                definition_id=definition_id,
            )
        unit_price = int(quote["buy"] if normalized_action == "BUY" else quote["sell"])
        if unit_price <= 0:
            return failure(
                "VENDOR_ITEM_NOT_FOR_SALE"
                if normalized_action == "BUY"
                else "VENDOR_ITEM_NOT_BUYING",
                vendor_id=resolved_vendor_id,
                instance_id=wanted_instance_id,
                definition_id=definition_id,
            )

        quantity = max(1, int(instance.get("quantity", 1))) if isinstance(instance, dict) else 0
        total_price = economy_contract.bounded_currency(unit_price * quantity)
        if buyback_price is not None:
            if normalized_action != "BUY" or type(buyback_price) is not int or not 0 < buyback_price <= economy_contract.MAX_CURRENCY:
                return failure("VENDOR_BUYBACK_PRICE_INVALID")
            total_price = buyback_price
        if total_price <= 0:
            return failure(
                "VENDOR_PRICE_INVALID",
                instance_id=wanted_instance_id,
                definition_id=definition_id,
            )
        if normalized_action == "BUY":
            if destination_slot is not None:
                self._ensure_inventory_slots_locked()
                if type(destination_slot) is not int or not 0 <= destination_slot < item_state.MAX_INVENTORY_SLOTS:
                    return failure("VENDOR_TARGET_SLOT_INVALID")
                if any(row.get("location") == "INVENTORY" and row.get("owner_id") == "player" and row.get("slot_index") == destination_slot for row in self._item_instances.values()):
                    return failure("VENDOR_TARGET_SLOT_OCCUPIED")
            if not isinstance(instance, dict):
                return failure("VENDOR_STOCK_INSTANCE_REQUIRED", instance_id=wanted_instance_id)
            if (
                str(instance.get("owner_id")) != identity_id
                or str(instance.get("location")) != "POCKET"
            ):
                return failure(
                    "VENDOR_STOCK_INSTANCE_INVALID",
                    instance_id=wanted_instance_id,
                    expected_owner=identity_id,
                    expected_location="POCKET",
                )
            if definition_id not in {str(value) for value in inventory_refs}:
                return failure(
                    "VENDOR_STOCK_REFERENCE_MISSING",
                    vendor_id=resolved_vendor_id,
                    instance_id=wanted_instance_id,
                    definition_id=definition_id,
                )
            inventory_slots = sum(
                1
                for row in self._item_instances.values()
                if isinstance(row, dict)
                and str(row.get("owner_id")) == "player"
                and str(row.get("location")) == "INVENTORY"
            )
            if inventory_slots >= item_state.MAX_INVENTORY_SLOTS:
                return failure(
                    "VENDOR_PLAYER_INVENTORY_FULL",
                    instance_id=wanted_instance_id,
                )
            if int(wallet.get("gold", 0)) < total_price:
                return failure(
                    "VENDOR_PLAYER_GOLD_INSUFFICIENT",
                    price=total_price,
                    gold=max(0, int(wallet.get("gold", 0))),
                )
            if int(account.get("gold", 0)) > economy_contract.MAX_CURRENCY - total_price:
                return failure("VENDOR_GOLD_CAPACITY", vendor_id=resolved_vendor_id)
        else:
            if not isinstance(instance, dict):
                return failure("VENDOR_PLAYER_INSTANCE_REQUIRED", instance_id=wanted_instance_id)
            if (
                str(instance.get("owner_id")) != "player"
                or str(instance.get("location")) != "INVENTORY"
            ):
                return failure(
                    "VENDOR_SELL_LOCATION_INVALID",
                    instance_id=wanted_instance_id,
                    expected_owner="player",
                    expected_location="INVENTORY",
                )
            if int(self._inventory.get(definition_id, 0)) < quantity:
                return failure(
                    "VENDOR_PLAYER_INVENTORY_DESYNC",
                    instance_id=wanted_instance_id,
                    definition_id=definition_id,
                )
            if len(inventory_refs) >= identity_contract.MAX_CARRIED_ITEMS:
                return failure("VENDOR_NPC_INVENTORY_FULL", npc_id=identity_id)
            pocket_count = sum(
                1
                for row in self._item_instances.values()
                if isinstance(row, dict) and str(row.get("location")) == "POCKET"
            )
            if pocket_count >= item_state.MAX_POCKET_ITEMS:
                return failure("VENDOR_NPC_POCKET_BUDGET", npc_id=identity_id)
            if int(account.get("gold", 0)) < total_price:
                return failure(
                    "VENDOR_GOLD_INSUFFICIENT",
                    vendor_id=resolved_vendor_id,
                    price=total_price,
                    gold=max(0, int(account.get("gold", 0))),
                )
            if int(wallet.get("gold", 0)) > economy_contract.MAX_CURRENCY - total_price:
                return failure("PLAYER_GOLD_CAPACITY")

        instance_backup = copy.deepcopy(instance)
        inventory_backup = dict(self._inventory)
        person_backup = copy.deepcopy(person)
        wallet_backup = copy.deepcopy(wallet)
        account_backup = copy.deepcopy(account)
        last_backup = copy.deepcopy(self._economy_state.get("last", {}))
        history_backup = copy.deepcopy(self._economy_state.get("history", []))
        interaction_count_backup = self._npc_interaction_count[npc_index]
        npc_gear_decision: dict[str, Any] = {}
        npc_power_result: dict[str, Any] = {}
        try:
            if normalized_action == "BUY":
                ok, transition = self._move_item_locked(
                    instance,
                    "INVENTORY",
                    owner_id="player",
                )
                if not ok:
                    raise ValueError(str(transition.get("error", "VENDOR_BUY_MOVE_FAILED")))
                if destination_slot is not None:instance["slot_index"] = destination_slot
                if not self._npc_remove_inventory_ref_locked(person, definition_id):
                    raise ValueError("VENDOR_STOCK_REFERENCE_REMOVE_FAILED")
                wallet["gold"] = int(wallet.get("gold", 0)) - total_price
                wallet["spent"] = economy_contract.bounded_currency(
                    int(wallet.get("spent", 0)) + total_price
                )
                account["gold"] = economy_contract.bounded_currency(
                    int(account.get("gold", 0)) + total_price
                )
                memory_text = f"Sold {str(instance.get('name', definition_id))} to the player."
                response = "A real purchase was completed from physical vendor stock."
            else:
                ok, transition = self._move_item_locked(
                    instance,
                    "POCKET",
                    owner_id=identity_id,
                )
                if not ok:
                    raise ValueError(str(transition.get("error", "VENDOR_SELL_MOVE_FAILED")))
                if not self._npc_add_inventory_ref_locked(person, definition_id):
                    raise ValueError("VENDOR_INVENTORY_REFERENCE_ADD_FAILED")
                upgraded = False
                if not reserve_buyback:
                    upgraded, npc_gear_decision = self._npc_equip_better_gear_locked(
                        identity_id, person, instance,
                    )
                if upgraded:
                    npc_gear_decision["gear_upgrade"] = True
                wallet["gold"] = economy_contract.bounded_currency(
                    int(wallet.get("gold", 0)) + total_price
                )
                wallet["earned"] = economy_contract.bounded_currency(
                    int(wallet.get("earned", 0)) + total_price
                )
                account["gold"] = int(account.get("gold", 0)) - total_price
                memory_text = f"Bought {str(instance.get('name', definition_id))} from the player."
                response = "A real sale was completed to a nearby vendor."
            wallet["revision"] = max(0, int(wallet.get("revision", 0))) + 1
            account["transactions"] = max(0, int(account.get("transactions", 0))) + 1
            account["revision"] = max(0, int(account.get("revision", 0))) + 1
            market = economy_contract.record_market_transaction(
                account,
                definition_id,
                normalized_action,
                self._sim_time,
            )
            self._npc_interaction_count[npc_index] += 1
            identity_contract.record_memory(
                self._individual_state,
                identity_id,
                "VENDOR_" + normalized_action,
                "player",
                self._sim_time,
                text=memory_text,
                weight=0.68,
            )
            npc_power_result = self._refresh_npc_progression_locked(
                identity_id,
                person,
                source="VENDOR_" + normalized_action,
            )
        except (TypeError, ValueError, KeyError, OverflowError) as exc:
            self._item_instances[wanted_instance_id] = instance_backup
            self._inventory = inventory_backup
            person.clear()
            person.update(person_backup)
            wallet.clear()
            wallet.update(wallet_backup)
            account.clear()
            account.update(account_backup)
            self._economy_state["last"] = last_backup
            self._economy_state["history"] = history_backup
            self._npc_interaction_count[npc_index] = interaction_count_backup
            return failure(
                "VENDOR_ATOMIC_ROLLBACK",
                vendor_id=resolved_vendor_id,
                npc_id=identity_id,
                instance_id=wanted_instance_id,
                cause=str(exc)[:96],
            )

        transaction = economy_contract.normalize_transaction(
            {
                "ok": True,
                "action": normalized_action,
                "vendor_id": resolved_vendor_id,
                "vendor_name": vendor.get("name", resolved_vendor_id),
                "npc_id": identity_id,
                "instance_id": wanted_instance_id,
                "definition_id": definition_id,
                "quantity": quantity,
                "unit_price": unit_price,
                "total_price": total_price,
                "distance_m": distance,
                "player_gold_after": wallet["gold"],
                "vendor_gold_after": account["gold"],
                "vendor_revision": account["revision"],
                "base_unit_price": quote["base_buy"
                if normalized_action == "BUY"
                else "base_sell"],
                "demand": quote["demand"],
                "stock": quote["stock"],
                "buy_multiplier": quote["buy_multiplier"],
                "sell_multiplier": quote["sell_multiplier"],
                "preference_priority": quote["preference_priority"],
                "target_stock": quote["target_stock"],
                "preference_gap": quote["preference_gap"],
                "atomic": True,
                "npc_gear_upgrade": npc_gear_decision,
                "npc_power": npc_power_result,
                "item": item_state.instance_view(
                    self._item_catalog,
                    instance,
                    sim_time=self._sim_time,
                ),
            }
        )
        self._economy_state["last"] = transaction
        history = self._economy_state.setdefault("history", [])
        if isinstance(history, list):
            history.append(copy.deepcopy(transaction))
            self._economy_state["history"] = history[-economy_contract.MAX_TRANSACTION_HISTORY:]
        self._last_item_interaction = transaction
        self._npc_last_interaction = {
            "id": identity_id,
            "entity_id": f"e-{npc_index:04d}",
            "archetype": self._npc_archetype[npc_index],
            "state": self._npc_state[npc_index],
            "distance_m": round(distance, 3),
            "interaction_count": self._npc_interaction_count[npc_index],
            "response": response,
        }
        event_kind = "VENDOR_BUY" if normalized_action == "BUY" else "VENDOR_SELL"
        self._append_event_locked(
            event_kind,
            f"{normalized_action.title()} {definition_id} with {resolved_vendor_id} for {total_price} gold.",
            actor_id="player",
            subject_id=wanted_instance_id,
            target_id=resolved_vendor_id,
            payload={
                "vendor_id": resolved_vendor_id,
                "npc_id": identity_id,
                "instance_id": wanted_instance_id,
                "definition_id": definition_id,
                "quantity": quantity,
                "unit_price": unit_price,
                "total_price": total_price,
                "base_unit_price": transaction.get("base_unit_price", 0),
                "demand": transaction.get("demand", 0),
                "stock": transaction.get("stock", 0),
                "market": market,
                "npc_gear_upgrade": copy.deepcopy(npc_gear_decision),
                "npc_power": copy.deepcopy(npc_power_result),
                "currency": "GOLD",
                "distance_m": round(distance, 3),
                "atomic": True,
            },
        )
        if npc_power_result.get("changed"):
            progression_state = person.get("progression", {})
            self._append_event_locked(
                "NPC_POWER_CHANGED",
                f"{identity_id} power is now {npc_power_result.get('power_score', 0)} "
                f"(gear {npc_power_result.get('gear_score', 0)}).",
                actor_id="player",
                subject_id="POWER",
                target_id=identity_id,
                payload={
                    "source": "VENDOR_" + normalized_action,
                    "power": copy.deepcopy(npc_power_result),
                    "progression": npc_progression.summary(progression_state),
                },
            )
        snapshot = self.snapshot_locked()
        snapshot["economy_result"] = copy.deepcopy(transaction)
        return snapshot

    def vendor_buy(
        self,
        vendor_id: str = "",
        instance_id: str = "",
    ) -> dict[str, Any]:
        with self._lock:
            return self._vendor_transaction_locked("BUY", vendor_id, instance_id)

    def vendor_sell(
        self,
        vendor_id: str = "",
        instance_id: str = "",
    ) -> dict[str, Any]:
        with self._lock:
            return self._vendor_transaction_locked("SELL", vendor_id, instance_id)

    def _terrain_target_cell_locked(
        self,
        cell_x: Any,
        cell_z: Any,
    ) -> tuple[int, int, dict[str, Any] | None]:
        """Resolve an authoring target against the currently loaded cells."""
        player_cell_x = world.chunk_coord(self._x[0])
        player_cell_z = world.chunk_coord(self._z[0])
        explicit = cell_x is not None or cell_z is not None
        if not explicit:
            target_x, target_z = player_cell_x, player_cell_z
        else:
            target_x = _cell_coordinate(cell_x)
            target_z = _cell_coordinate(cell_z)
            if target_x is None or target_z is None:
                return player_cell_x, player_cell_z, {
                    "error": "GAME_ENGINE_TERRAIN_CELL_INVALID",
                    "target": {"x": target_x, "z": target_z},
                }

        loaded_keys = {
            str(row.get("key"))
            for row in world.interest_cells(
                self._x[0],
                self._z[0],
                radius=world.DEFAULT_INTEREST_RADIUS,
            )
            if isinstance(row, dict) and row.get("key")
        }
        target_key = world.cell_key(target_x, target_z)
        if target_key not in loaded_keys:
            return target_x, target_z, {
                "error": "GAME_ENGINE_TERRAIN_CELL_NOT_LOADED",
                "target": {
                    "key": target_key,
                    "x": target_x,
                    "z": target_z,
                },
                "loaded_cells": sorted(loaded_keys),
            }
        return target_x, target_z, None

    def terrain_edit(
        self,
        operation: str = "RAISE",
        cell_x: int | None = None,
        cell_z: int | None = None,
    ) -> dict[str, Any]:
        """Apply one safe authoring command to a loaded cell."""
        normalized = str(operation or "RAISE").upper()
        if normalized not in terrain_contract.EDIT_OPERATIONS:
            return {
                "schema": SCHEMA,
                "error": "GAME_ENGINE_TERRAIN_OPERATION_INVALID",
                "allowed": list(terrain_contract.EDIT_OPERATIONS),
            }
        with self._lock:
            target_x, target_z, target_error = self._terrain_target_cell_locked(
                cell_x, cell_z
            )
            if target_error is not None:
                snapshot = self.snapshot_locked()
                snapshot["error"] = target_error.get(
                    "error", "GAME_ENGINE_TERRAIN_TARGET_INVALID"
                )
                snapshot["terrain_edit_result"] = target_error
                return snapshot
            player_cell_x = world.chunk_coord(self._x[0])
            player_cell_z = world.chunk_coord(self._z[0])
            current = terrain_contract.override_for(
                self._terrain_overrides, target_x, target_z
            )
            current_height = float(current["height_delta_m"]) if current else 0.0
            height_delta: float | None = None
            biome: str | None = None
            water_mode: str | None = None
            clear = normalized == "CLEAR"
            if normalized == "RAISE":
                height_delta = current_height + 1.0
            elif normalized == "LOWER":
                height_delta = current_height - 1.0
            elif normalized == "LAND":
                water_mode = "LAND"
            elif normalized == "WATER":
                water_mode = "WATER"
            elif normalized == "REEF":
                biome = "REEF"
            elif normalized == "ISLAND":
                biome = "FIRST_ISLAND"
                water_mode = "LAND"
            ok, result = terrain_contract.apply_override(
                self._terrain_overrides,
                target_x,
                target_z,
                height_delta_m=height_delta,
                biome=biome,
                water_mode=water_mode,
                clear=clear,
            )
            result["target"] = {
                "key": world.cell_key(target_x, target_z),
                "x": target_x,
                "z": target_z,
                "source": (
                    "EXPLICIT_CELL"
                    if cell_x is not None or cell_z is not None
                    else "PLAYER_CELL"
                ),
            }
            snapshot = self.snapshot_locked()
            if not ok:
                snapshot["error"] = result.get("error", "TERRAIN_EDIT_FAILED")
                snapshot["terrain_edit_result"] = result
                return snapshot
            if (
                self._movement_mode == "GROUND"
                and target_x == player_cell_x
                and target_z == player_cell_z
            ):
                self._y[0] = self._terrain_height_locked(
                    self._x[0], self._z[0]
                ) + 0.65
            self._append_event_locked(
                "TERRAIN_EDIT",
                f"{normalized.lower()} applied to cell {target_x}:{target_z}.",
            )
            snapshot = self.snapshot_locked()
            snapshot["terrain_edit_result"] = result
            return snapshot

    def terrain_brush_edit(
        self,
        operation: str = "RAISE",
        cell_x: int | None = None,
        cell_z: int | None = None,
        center_x_m: float | None = None,
        center_z_m: float | None = None,
        radius_m: float = 4.0,
        falloff: str = "SMOOTH",
    ) -> dict[str, Any]:
        """Apply a height brush at a sub-cell point on a loaded cell."""
        normalized = str(operation or "RAISE").upper()
        if normalized not in {"RAISE", "LOWER"}:
            return self.terrain_edit(normalized, cell_x, cell_z)
        with self._lock:
            target_x, target_z, target_error = self._terrain_target_cell_locked(
                cell_x, cell_z
            )
            if target_error is not None:
                snapshot = self.snapshot_locked()
                snapshot["error"] = target_error.get(
                    "error", "GAME_ENGINE_TERRAIN_TARGET_INVALID"
                )
                snapshot["terrain_brush_result"] = target_error
                return snapshot
            player_cell_x = world.chunk_coord(self._x[0])
            player_cell_z = world.chunk_coord(self._z[0])
            if center_x_m is None:
                center_x_m = (
                    self._x[0]
                    if target_x == player_cell_x and target_z == player_cell_z
                    else (target_x + 0.5) * CHUNK_SIZE
                )
            if center_z_m is None:
                center_z_m = (
                    self._z[0]
                    if target_x == player_cell_x and target_z == player_cell_z
                    else (target_z + 0.5) * CHUNK_SIZE
                )
            strength = 1.0 if normalized == "RAISE" else -1.0
            ok, result = terrain_contract.apply_brush(
                self._terrain_overrides,
                target_x,
                target_z,
                center_x_m=center_x_m,
                center_z_m=center_z_m,
                radius_m=radius_m,
                strength_m=strength,
                falloff=falloff,
            )
            result["target"] = {
                "key": world.cell_key(target_x, target_z),
                "x": target_x,
                "z": target_z,
                "source": (
                    "EXPLICIT_CELL"
                    if cell_x is not None or cell_z is not None
                    else "PLAYER_CELL"
                ),
            }
            if isinstance(result.get("stamp"), dict):
                result["brush"] = dict(result["stamp"])
            snapshot = self.snapshot_locked()
            if not ok:
                snapshot["error"] = result.get(
                    "error", "TERRAIN_BRUSH_EDIT_FAILED"
                )
                snapshot["terrain_brush_result"] = result
                return snapshot
            if (
                self._movement_mode == "GROUND"
                and target_x == player_cell_x
                and target_z == player_cell_z
            ):
                self._y[0] = self._terrain_height_locked(
                    self._x[0], self._z[0]
                ) + 0.65
            stamp = result.get("stamp", {})
            self._append_event_locked(
                "TERRAIN_BRUSH",
                f"{normalized.lower()} brush on cell {target_x}:{target_z} "
                f"({stamp.get('radius_m', radius_m)} m).",
            )
            snapshot = self.snapshot_locked()
            snapshot["terrain_brush_result"] = result
            snapshot["terrain_edit_result"] = result
            return snapshot

    def terrain_undo(self) -> dict[str, Any]:
        """Undo the latest cell authoring command."""
        with self._lock:
            ok, result = terrain_contract.undo_override(self._terrain_overrides)
            snapshot = self.snapshot_locked()
            if not ok:
                snapshot["error"] = result.get("error", "TERRAIN_UNDO_FAILED")
                snapshot["terrain_edit_result"] = result
                return snapshot
            undo_key = str(result.get("key", ""))
            player_key = world.cell_key(
                world.chunk_coord(self._x[0]),
                world.chunk_coord(self._z[0]),
            )
            if self._movement_mode == "GROUND" and undo_key == player_key:
                self._y[0] = self._terrain_height_locked(
                    self._x[0], self._z[0]
                ) + 0.65
            self._append_event_locked(
                "TERRAIN_UNDO",
                f"Restored terrain cell {result.get('key', '')}.",
            )
            snapshot = self.snapshot_locked()
            snapshot["terrain_edit_result"] = result
            return snapshot

    def save_state(self, *, snapshot: bool = True) -> dict[str, Any]:
        with self._lock:
            from backend import game_engine_adapter_world_state as mounted_world_state
            # Record the transition before serializing so the saved journal
            # contains the save boundary itself without a second revision.
            self._append_event_locked(
                "SAVE",
                "Saved local player state.",
                actor_id="player",
                subject_id=self._persistence_key,
            )
            self._instance_checkpoint_world_locked()
            payload = mmo.persistent_payload(
                player={
                    "x": self._x[0],
                    "y": self._y[0],
                    "z": self._z[0],
                    "yaw": self._yaw[0],
                    "vx": self._vx[0],
                    "vy": self._vy[0],
                    "vz": self._vz[0],
                    "jump_count": self._jump_count,
                    "double_jump_pose_remaining_s": self._double_jump_pose_remaining_s,
                    "client_controls": self._client_controls_save_locked(),
                },
                movement_mode=self._movement_mode,
                inventory=self._inventory,
                loot_items=self._loot_items,
                progression=self._progression,
                editor_document=self._editor_document,
                terrain_overrides=self._terrain_overrides,
                keybindings=self._keybindings,
                addons=self._addons,
                item_instances=list(self._item_instances.values()),
                profession_state=self._profession_state,
                npc_individuals=self._individual_state,
                event_journal=self._event_journal,
                trade_state=self._last_trade,
                economy_state=self._economy_state,
                combat_state=self._combat_state,
                quest_state=self._quest_state,
                faction_state=self._faction_state,
                dialogue_state=self._dialogue_state,
                social_state=self._social_state,
                living_world_state={
                    "nature": self._nature.save(self._sim_time),
                    "actions": self._actions.save(),
                    "promoted_ids": sorted(self._promoted_life_ids)[:MAX_POPULATION_PROMOTIONS],
                    "last_promotion_s": self._last_population_promotion_s,
                    "regional_population": self._world_population.save(),
                },
                world_event_state=self._world_event_state,
                content_state={
                    "active_packs": list(self._active_content_pack_ids),
                    "mounted_world": mounted_world_state.capture(self),
                },
                simulation_state={
                    "tick": self._tick,
                    "time_s": self._sim_time,
                    "network_seq": self._network_seq,
                },
            )
            result = self._state_store.save(self._persistence_key, payload)
            self._persistence_revision = int(result["revision"])
            if not snapshot:
                return result
            view = self.snapshot_locked()
            view["persistence_result"] = result
            return view

    def load_state(self) -> dict[str, Any]:
        with self._lock:
            payload = self._state_store.load(self._persistence_key)
            if not isinstance(payload, dict):
                snapshot = self.snapshot_locked()
                snapshot["error"] = "PERSISTENCE_STATE_MISSING"
                return snapshot
            # Reject hidden payloads before changing targets, content packs,
            # promoted actors, player position or the authoritative registry.
            for source in ('item_instances','loot_items'):
                rows=payload.get(source)
                if isinstance(rows,list) and any(not item_state.saved_gift_payload_valid(row) for row in rows):
                    result=self.snapshot_locked();result['error']='ITEM_SAVE_GIFT_PAYLOAD_INVALID';return result
            from backend import game_engine_adapter_world_state as mounted_world_state
            try:
                saved_mounted_world = mounted_world_state.read(payload)
            except (ValueError, TypeError, OSError) as exc:
                result=self.snapshot_locked();result['error']=str(exc)[:240];return result
            mounted_world_state.detach_for_load(self)
            self._instance_prepare_load_locked()
            self._combat_target_id = ""
            saved_content = payload.get("content_state")
            saved_pack_ids = (
                saved_content.get("active_packs", [])
                if isinstance(saved_content, dict)
                else []
            )
            content_changed = False
            if isinstance(saved_pack_ids, list):
                for pack_id in saved_pack_ids[:8]:
                    wanted_pack = str(pack_id).strip()[:64]
                    if (
                        wanted_pack
                        and wanted_pack in self._available_content_packs
                        and wanted_pack not in self._active_content_pack_ids
                    ):
                        self._content = content_catalog.merge_content_pack(
                            self._content,
                            self._available_content_packs[wanted_pack],
                        )
                        self._active_content_pack_ids.append(wanted_pack)
                        content_changed = True
                if content_changed:
                    self._rebuild_content_runtime_locked()
            # Rebuild the ambient/physical boundary before applying the saved
            # world. Promoted residents are physical pool rows, while their
            # source definitions remain in the authored ambient catalogue.
            # Removing only those rows avoids touching editor placements or
            # the authored starter NPCs.
            for index in tuple(self._npc_indices):
                if str(self._npc_ids[index]) in self._promoted_life_ids:
                    self._despawn_entity_locked(index)
            self._set_life_spawns_locked(life_contract.spawns_from_content(self._content))
            self._promoted_life_ids = set()
            self._last_population_promotion_s = 0.0
            player = payload.get("player", {})
            if isinstance(player, dict):
                self._x[0] = _clamp(player.get("x"), -1000000.0, 1000000.0)
                self._y[0] = _clamp(player.get("y"), 0.0, 1000000.0, 0.65)
                self._z[0] = _clamp(player.get("z"), -1000000.0, 1000000.0)
                self._yaw[0] = _clamp(player.get("yaw"), -1000000.0, 1000000.0)
                self._vx[0] = _clamp(player.get("vx"), -1000.0, 1000.0)
                self._vy[0] = _clamp(player.get("vy"), -1000.0, 1000.0)
                self._vz[0] = _clamp(player.get("vz"), -1000.0, 1000.0)
                self._jump_count = int(_clamp(player.get("jump_count"), 0.0, 2.0))
                self._double_jump_pose_remaining_s = _clamp(
                    player.get("double_jump_pose_remaining_s"),
                    0.0,
                    animation_contract.DOUBLE_JUMP_ANIMATION_SECONDS,
                )
                self._restore_client_controls_locked(player.get('client_controls'))
                self._reset_spells_locked()
            self._movement_mode = world.normalize_movement_mode(
                payload.get("movement_mode"), "GROUND"
            )
            self._input["movement_mode"] = self._movement_mode
            inventory = payload.get("inventory", {})
            self._inventory = (
                {
                    str(key): max(0, int(value))
                    for key, value in inventory.items()
                    if isinstance(key, str)
                }
                if isinstance(inventory, dict)
                else {}
            )
            loot_items = payload.get("loot_items", [])
            saved_item_instances = payload.get("item_instances")
            if isinstance(saved_item_instances, list):
                self._item_instances = {}
                for raw_item in saved_item_instances[-item_state.MAX_WORLD_INSTANCES:]:
                    normalized_item = item_state.normalize_instance(
                        self._item_catalog,
                        raw_item,
                    )
                    if normalized_item is not None:
                        self._item_instances[str(normalized_item["instance_id"])] = normalized_item
            self._loot_items = []
            if isinstance(loot_items, list):
                for raw_item in loot_items[-64:]:
                    if not isinstance(raw_item, dict):
                        continue
                    instance_id = str(raw_item.get("instance_id", ""))
                    item = self._item_instances.get(instance_id)
                    if item is None:
                        item = item_state.normalize_instance(self._item_catalog, raw_item)
                        if item is not None:
                            self._item_instances[instance_id] = item
                    if item is not None:
                        self._loot_items.append(item)
            self._item_counter = 0
            self._reconcile_item_instances_locked()
            self._individual_state = identity_contract.restore_state(
                payload.get("npc_individuals"),
                self._people_catalog,
            )
            self._ensure_life_individuals_locked()
            self._faction_state = factions_contract.normalize_state(
                payload.get("faction_state"),
                self._people_catalog.values(),
            )
            self._quest_state = quests_contract.normalize_state(
                payload.get("quest_state"),
                self._quest_catalog,
            )
            self._combat_state = combat_contract.normalize_state(
                payload.get("combat_state")
            )
            self._lifecycle_loaded_locked()
            self._dialogue_state = dialogue_contract.normalize_state(
                payload.get("dialogue_state")
            )
            self._engine_quest_panel={};self._engine_gossip_hidden=False
            self._social_state = social_contract.normalize_state(
                payload.get("social_state")
            )
            self._world_event_state = world_events_contract.normalize_state(
                payload.get("world_event_state"),
                self._world_event_catalog,
            )
            saved_simulation = payload.get("simulation")
            if isinstance(saved_simulation, dict):
                self._tick = max(
                    0,
                    int(_clamp(saved_simulation.get("tick"), 0.0, 2_000_000_000.0, self._tick)),
                )
                self._sim_time = max(
                    0.0,
                    _clamp(saved_simulation.get("time_s"), 0.0, 1_000_000_000.0),
                )
                self._network_seq = max(
                    0,
                    int(_clamp(
                        saved_simulation.get("network_seq"),
                        0.0,
                        2_000_000_000.0,
                        self._network_seq,
                    )),
                )
            saved_living_world = payload.get("living_world_state")
            saved_promoted_ids: list[str] = []
            self._world_population = WorldPopulation()
            self._world_actor_assets = {}
            if isinstance(saved_living_world, dict):
                self._world_population.restore(saved_living_world.get('regional_population'))
                self._nature.restore(saved_living_world.get("nature"), self._sim_time)
                self._actions.restore(saved_living_world.get("actions"),self._content.get("abilities",{}),self._action_definitions_locked())
                raw_promoted_ids = saved_living_world.get("promoted_ids", [])
                if isinstance(raw_promoted_ids, list):
                    saved_promoted_ids = list(
                        dict.fromkeys(
                            str(value).strip()
                            for value in raw_promoted_ids[:MAX_POPULATION_PROMOTIONS]
                            if str(value).strip()
                        )
                    )
                self._last_population_promotion_s = _clamp(
                    saved_living_world.get("last_promotion_s"),
                    0.0,
                    1_000_000_000.0,
                )
            for spawn in tuple(self._life_spawns):
                if str(spawn.get("id", "")) not in saved_promoted_ids:
                    continue
                self._promote_life_actor_locked(spawn, record_event=False)
            self._last_combat = copy.deepcopy(
                self._combat_state.get("last_event", {})
                if isinstance(self._combat_state, dict)
                else {}
            )
            self._materialize_npc_item_instances_locked()
            self._refresh_all_npc_progression_locked()
            self._sync_npc_combat_presence_locked()
            self._battlefield_loaded_locked()
            self._last_trade = trade_contract.restore(payload.get("trade_state"))
            self._economy_state = economy_contract.restore_state(
                payload.get("economy_state"),
                self._vendor_catalog,
            )
            self._event_journal = events_contract.restore(
                payload.get("event_journal")
            )
            saved_professions = payload.get("profession_state")
            self._profession_state = (
                copy.deepcopy(saved_professions)
                if isinstance(saved_professions, dict)
                else copy.deepcopy(self._gear_tables.get("professions", {}))
            )
            saved_progression = payload.get("progression")
            self._progression = (
                progression.summary(saved_progression)
                if isinstance(saved_progression, dict)
                else progression.starter_state()
            )
            self._terrain_overrides = terrain_contract.clone_overrides(
                payload.get("terrain_overrides")
            )
            self._keybindings = input_contract.normalize_bindings(
                payload.get("keybindings")
            )
            self._addons = addons_contract.normalize_state(payload.get("addons"))
            if self._movement_mode == "GROUND":
                self._y[0] = self._terrain_height_locked(
                    self._x[0], self._z[0]
                ) + 0.65

            for slot in tuple(self._editor_entity_indices.values()):
                self._despawn_entity_locked(slot)
            self._editor_entity_indices = {}
            saved_editor = payload.get("editor")
            self._editor_document = (
                editor_contract.clone_document(saved_editor)
                if isinstance(saved_editor, dict)
                else editor_contract.new_document()
            )
            for placement in self._editor_document.get("placements", []):
                if not isinstance(placement, dict):
                    continue
                placement_kind = editor_contract.normalize_kind(
                    placement.get("kind", "PROP")
                )
                if placement_kind == "NPC":
                    slot = self._spawn_npc_locked(
                        {
                            "id": f"editor-{placement.get('id', 'npc')}",
                            "archetype": "WANDERER",
                            "x": _clamp(placement.get("x"), -1000000.0, 1000000.0),
                            "z": _clamp(placement.get("z"), -1000000.0, 1000000.0),
                            "scale": (
                                _clamp(placement.get("sx"), 0.05, 12.0, 1.0),
                                _clamp(placement.get("sy"), 0.05, 12.0, 1.0),
                                _clamp(placement.get("sz"), 0.05, 12.0, 1.0),
                            ),
                            "color": str(placement.get("color", "#d7a36f")),
                            "phase": float(self._editor_document.get("revision", 0)) * 0.73,
                        }
                    )
                else:
                    slot = self._spawn_entity_locked(
                        f"EDITOR_{placement_kind}",
                        _clamp(placement.get("x"), -1000000.0, 1000000.0),
                        _clamp(placement.get("y"), 0.0, 1000000.0, 0.8),
                        _clamp(placement.get("z"), -1000000.0, 1000000.0),
                        (
                            _clamp(placement.get("sx"), 0.05, 12.0, 1.0),
                            _clamp(placement.get("sy"), 0.05, 12.0, 1.0),
                            _clamp(placement.get("sz"), 0.05, 12.0, 1.0),
                        ),
                        str(placement.get("color", "#8fa8a0")),
                        0.8,
                    )
                if slot is not None:
                    placement_id = str(placement.get("id", ""))
                    editor_contract.attach_entity(
                        self._editor_document,
                        placement_id,
                        f"e-{slot:04d}",
                    )
                    self._editor_entity_indices[placement_id] = slot
            self._instance_loaded_locked()
            mounted_world_state.arm(self, saved_mounted_world, player)
            self._persistence_revision = self._state_store.revision
            self._append_event_locked("LOAD", "Restored local player state.")
            snapshot = self.snapshot_locked()
            snapshot["persistence_result"] = {
                "schema": mmo.PERSISTENCE_SCHEMA,
                "key": self._persistence_key,
                "revision": self._persistence_revision,
                "mode": getattr(self._state_store, "mode", "MEMORY_ONLY"),
            }
            return snapshot

    def set_render_profile(self, profile: str) -> dict[str, Any]:
        normalized = render_contract.normalize_profile(profile, "")
        if not normalized:
            return {
                "schema": SCHEMA,
                "error": "GAME_ENGINE_RENDER_PROFILE_INVALID",
                "allowed": list(render_contract.PROFILE_NAMES),
            }
        with self._lock:
            self._render_profile = normalized
            self._append_event_locked(
                "RENDER_PROFILE",
                f"Render budget set to {normalized.lower()}.",
            )
            return self.snapshot_locked()

    def set_presentation_mode(self, mode: str) -> dict[str, Any]:
        """Switch only the presentation stage; simulation state stays intact."""
        normalized = render_contract.normalize_presentation_mode(mode, "")
        if not normalized:
            return {
                "schema": SCHEMA,
                "error": "GAME_ENGINE_PRESENTATION_MODE_INVALID",
                "allowed": list(render_contract.PRESENTATION_MODES),
            }
        with self._lock:
            self._presentation_mode = normalized
            self._presentation_reason = (
                "MANUAL_DOS_MODE" if normalized == render_contract.DOS_2D else ""
            )
            self._append_event_locked(
                "PRESENTATION_MODE",
                "DOS fallback renderer enabled."
                if normalized == render_contract.DOS_2D
                else "Rich 3D renderer restored.",
            )
            return self.snapshot_locked()

    def report_graphics_failure(self, reason: str = "GRAPHICS_STAGE_FAILURE") -> dict[str, Any]:
        """Enter the terminal renderer without resetting the world."""
        safe_reason = str(reason or "GRAPHICS_STAGE_FAILURE").strip()[:96]
        with self._lock:
            self._presentation_mode = render_contract.DOS_2D
            self._presentation_reason = safe_reason or "GRAPHICS_STAGE_FAILURE"
            self._append_event_locked(
                "GRAPHICS_FALLBACK",
                f"Rich renderer unavailable; continuing in DOS mode ({self._presentation_reason}).",
            )
            return self.snapshot_locked()

    def set_cinematic_preset(self, preset: str) -> dict[str, Any]:
        normalized = cinematic.normalize_preset(preset, "")
        if not normalized:
            return {
                "schema": SCHEMA,
                "error": "GAME_ENGINE_CINEMATIC_PRESET_INVALID",
                "allowed": list(cinematic.PRESETS),
            }
        with self._lock:
            self._cinematic_preset = normalized
            self._append_event_locked(
                "CINEMATIC",
                f"Composition preset set to {normalized.lower()}.",
            )
            return self.snapshot_locked()

    def burst(self) -> dict[str, Any]:
        with self._lock:
            self._burst_locked(self._x[0], 0.9, self._z[0], 48)
            return self.snapshot_locked()

    def set_stress(self, enabled: bool) -> dict[str, Any]:
        with self._lock:
            was_running = self._running
            self._stress = bool(enabled)
            self._running = False
            self._reset_world_locked()
            if was_running:
                self._running = True
            self._append_event_locked(
                "STRESS",
                "Stress scene enabled." if self._stress else "Stress scene disabled.",
            )
            return self.snapshot_locked()

    def start_recording(self) -> dict[str, Any]:
        with self._lock:
            self._recorded_inputs = []
            self._recording = True
            self._append_event_locked("RECORD", "Input recording armed; maximum 30 seconds.")
            return self.snapshot_locked()

    def stop_recording(self) -> dict[str, Any]:
        with self._lock:
            self._recording = False
            self._append_event_locked(
                "RECORD_STOP",
                f"Recorded {len(self._recorded_inputs)} fixed-step inputs.",
            )
            return self.snapshot_locked()

    def play_replay(self) -> dict[str, Any]:
        with self._lock:
            if not self._recorded_inputs:
                self._append_event_locked("REPLAY_EMPTY", "Record a run before replaying it.")
                return self.snapshot_locked()
            self._replay_inputs = list(self._recorded_inputs)
            self._replay_index = 0
            self._replaying = True
            self._running = True
            self._reset_world_locked()
            self._append_event_locked("REPLAY", "Replaying the recorded fixed-step input stream.")
            return self.snapshot_locked()

    @staticmethod
    def _compact_render_item_view(view: Any) -> dict[str, Any]:
        """Keep only item fields consumed by the 3D delegate."""
        if not isinstance(view, dict):
            return {}
        visual = view.get("visual")
        asset = view.get("asset")
        attachment = view.get("attachment")
        return {
            "instance_id": view.get("instance_id", ""),
            "definition_id": view.get("definition_id", ""),
            "name": view.get("name", ""),
            "kind": view.get("kind", "ITEM"),
            "location": view.get("location", ""),
            "owner_id": view.get("owner_id", ""),
            "equipped_slot": view.get("equipped_slot", ""),
            "rarity": view.get("rarity", "COMMON"),
            "rarity_color": view.get("rarity_color", ""),
            "craft_quality": view.get("craft_quality", "STANDARD"),
            "visual_phase": view.get('visual_phase', 0),
            "visual_visible": view.get('visual_visible', True),
            "visual_stowed": view.get('visual_stowed', False),
            "attachment": dict(attachment) if isinstance(attachment, dict) else {},
            "visual": dict(visual) if isinstance(visual, dict) else {},
            "asset": dict(asset) if isinstance(asset, dict) else {},
        }

    @classmethod
    def _compact_render_entity_row(cls, row: Any) -> dict[str, Any]:
        """Strip identity/inventory inspector payload from a render row."""
        if not isinstance(row, dict):
            return {}
        compact = {
            key: row.get(key)
            for key in (
                "id",
                "kind",
                "x",
                "y",
                "z",
                "yaw",
                "sx",
                "sy",
                "sz",
                "color",
                "speed",
                "motion_state",
                "animation",
                "asset",
                "cell_key",
                "lod",
            )
        }
        compact["asset"] = (
            dict(row["asset"]) if isinstance(row.get("asset"), dict) else None
        )
        compact["animation"] = (
            dict(row["animation"])
            if isinstance(row.get("animation"), dict)
            else None
        )
        equipment = row.get("equipment")
        compact["equipment"] = [
            cls._compact_render_item_view(item)
            for item in equipment[: item_state.MAX_EQUIPPED_ITEMS]
            if isinstance(item, dict)
        ] if isinstance(equipment, list) else []
        compact["item"] = (
            cls._compact_render_item_view(row["item"])
            if isinstance(row.get("item"), dict)
            else None
        )
        individual = row.get("individual")
        compact["individual"] = {
            key: individual[key]
            for key, maximum in (("id", 128), ("name", 512))
            if isinstance(individual, dict)
            and isinstance(individual.get(key), str)
            and len(individual[key].encode("utf-8")) <= maximum
        } if isinstance(individual, dict) else None
        return compact

    def _render_structure_signature_locked(self) -> tuple[Any, ...]:
        regional_ids=self._world_population.select(self._sim_time,self._x[0],self._z[0])
        """Separate scene changes from changes to the environment template."""
        entity_signature = tuple(
            (
                index,
                self._kind[index],
                self._npc_ids[index],
                round(self._sx[index], 3),
                round(self._sy[index], 3),
                round(self._sz[index], 3),
                self._color[index],
            )
            for index in self._active_entity_indices
        )
        item_signature: list[tuple[Any, ...]] = []
        for instance_id in sorted(self._item_instances):
            row = self._item_instances[instance_id]
            if not isinstance(row, dict):
                continue
            position = row.get("position")
            position = position if isinstance(position, dict) else {}
            item_signature.append(
                (
                    str(instance_id),
                    str(row.get("location", "")),
                    str(row.get("owner_id", "")),
                    str(row.get("definition_id", "")),
                    str(row.get("kind", "")),
                    str(row.get("equipped_slot", "")),
                    str(row.get("container_id", "")),
                    _safe_int(row.get("quantity"), 1),
                    str(row.get("rarity", "")),
                    _round(_clamp(position.get("x"), -1000000.0, 1000000.0)),
                    _round(_clamp(position.get("y"), -1000000.0, 1000000.0)),
                    _round(_clamp(position.get("z"), -1000000.0, 1000000.0)),
                    repr(row.get("sockets", [])),
                    repr(row.get("enchantments", [])),
                    repr(row.get("affixes", [])),
                )
            )
        life_signature = tuple(
            json.dumps(row, sort_keys=True, separators=(",", ":"), default=str)
            for row in self._life_spawns
            if isinstance(row, dict)
        )
        life_signature += tuple(('WORLD_RESIDENT',identity) for identity in regional_ids)
        return (
            entity_signature,
            tuple(item_signature),
            life_signature,
            tuple(sorted(self._promoted_life_ids)),
            self._render_environment_signature_locked(),
        )

    def _render_environment_signature_locked(self) -> tuple[Any, ...]:
        # Movement mode is live pose data, already refreshed by the compact
        # stream. Changing it does not invalidate terrain or asset metadata.
        return (
            tuple(self._active_content_pack_ids),
            tuple(sorted(str(key) for key in self._asset_catalog)),
            int(self._terrain_overrides.get("revision", 0)),
            self._render_profile,
            self._presentation_mode,
            self._presentation_reason,
            bool(self._stress),
        )

    def _dos_motion_signature_locked(
        self,
        rows: list[dict[str, Any]],
    ) -> tuple[Any, ...]:
        """Pose facts that change the DOS picture.  Sub-centimetre noise does not."""
        actors: list[tuple[Any, ...]] = []
        for row in rows:
            if str(row.get("kind", "")) not in {"NPC", "ACTOR"}:
                continue
            try:
                actors.append(
                    (
                        str(row.get("id", "")),
                        round(float(row.get("x", 0.0) or 0.0), 2),
                        round(float(row.get("z", 0.0) or 0.0), 2),
                        round(float(row.get("yaw", 0.0) or 0.0), 2),
                    )
                )
            except (TypeError, ValueError):
                continue
            if len(actors) >= 24:
                break
        return (
            round(float(self._x[0]), 2),
            round(float(self._y[0]), 2),
            round(float(self._z[0]), 2),
            round(float(self._yaw[0]), 3),
            tuple(actors),
        )

    def _live_dos_fallback_locked(
        self,
        rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Project the current pose into the cell frame carried on the render stream.

        The full snapshot builds this picture too, but QML movement reads the
        compact render stream and that stream used to drop ``fallback``.  The
        canvas then kept the frame from the moment DOS was selected.  Rebuilding
        here is what makes walking and turning visible while the low-poly view
        is hidden.
        """
        cache = self._render_snapshot_cache or {}
        shell = cache.get("dos_shell")
        shell = shell if isinstance(shell, dict) else {}
        terrain = cache.get("dos_terrain")
        terrain = terrain if isinstance(terrain, list) else []
        motion = self._dos_motion_signature_locked(rows)
        now = time.perf_counter()
        frame = self._dos_live_frame
        due = (now - self._dos_live_frame_at) >= DOS_FRAME_INTERVAL_S
        if frame is None or (due and motion != self._dos_live_motion):
            frame = fallback_contract.build_cell_frame(
                rows,
                terrain,
                player_x=self._x[0],
                player_y=self._y[0],
                player_z=self._z[0],
                player_yaw=self._yaw[0],
            )
            self._dos_live_frame = frame
            self._dos_live_motion = motion
            self._dos_live_frame_at = now
        terminal = shell.get("terminal")
        terminal = dict(terminal) if isinstance(terminal, dict) else {}
        lines = [
            str(line)
            for line in terminal.get("lines", [])
            if isinstance(line, (str, int, float))
        ]
        position = f"POS {self._x[0]:.1f},{self._z[0]:.1f}"
        for index, line in enumerate(lines):
            if line.startswith("POS "):
                lines[index] = position
                break
        else:
            lines.insert(0, position)
        terminal["lines"] = lines[: fallback_contract.MAX_TERMINAL_LINES]
        if "title" not in terminal:
            terminal["title"] = "GG//DOS FRONTIER"
        if "prompt" not in terminal:
            terminal["prompt"] = ">"
        palette = shell.get("palette")
        return {
            "schema": shell.get("schema", fallback_contract.SCHEMA),
            "version": shell.get("version", 1),
            "mode": shell.get("mode", fallback_contract.MODE),
            "renderer": shell.get("renderer", "QTQUICK_CANVAS_TERMINAL"),
            "palette": dict(palette) if isinstance(palette, dict) else {},
            "camera": {
                "center_x": round(float(self._x[0]), 3),
                "center_y": round(float(self._y[0]), 3),
                "center_z": round(float(self._z[0]), 3),
                "yaw": round(float(self._yaw[0]), 4),
                "radius_m": 18.0,
            },
            "frame": frame,
            "terminal": terminal,
            "terrain": terrain,
            "shared_contract": shell.get(
                "shared_contract",
                "AUTHORITATIVE_FIXED_STEP_ENTITY_ITEM_NPC_DATA",
            ),
            "policy": shell.get(
                "policy",
                "BOUNDED_2D_FALLBACK_RENDERER_NO_SIMULATION_MUTATION",
            ),
        }

    def _remember_render_snapshot_locked(self, snapshot: dict[str, Any]) -> None:
        """Cache a compact render template after a full authoritative snapshot."""
        render = snapshot.get("render")
        render = render if isinstance(render, dict) else {}
        entities = render.get("entities")
        entities = entities if isinstance(entities, list) else []
        particles = render.get("particles")
        particles = particles if isinstance(particles, list) else []
        render_meta = {
            key: value
            for key, value in render.items()
            if key not in {"entities", "particles", "fallback"}
        }
        player = snapshot.get("player")
        player = player if isinstance(player, dict) else {}
        fallback = render.get("fallback")
        fallback = fallback if isinstance(fallback, dict) else {}
        terrain = fallback.get("terrain")
        palette = fallback.get("palette")
        terminal = fallback.get("terminal")
        frame = fallback.get("frame")
        compact_rows = [
            self._compact_render_entity_row(row)
            for row in entities
            if isinstance(row, dict)
        ]
        self._render_snapshot_cache = {
            "state": str(snapshot.get("state", "IDLE")),
            "stress": bool(snapshot.get("stress", False)),
            "player": dict(player),
            "render_meta": render_meta,
            "entities": compact_rows,
            "particles": [
                dict(row) for row in particles if isinstance(row, dict)
            ],
            "dos_terrain": [
                {
                    "x": row.get("x", 0.0),
                    "z": row.get("z", 0.0),
                    "surface": row.get("surface", "LAND"),
                    "biome": row.get("biome", ""),
                }
                for row in terrain
                if isinstance(row, dict)
            ] if isinstance(terrain, list) else [],
            "dos_shell": {
                "schema": fallback.get("schema", fallback_contract.SCHEMA),
                "version": fallback.get("version", 1),
                "mode": fallback.get("mode", fallback_contract.MODE),
                "renderer": fallback.get("renderer", "QTQUICK_CANVAS_TERMINAL"),
                "palette": dict(palette) if isinstance(palette, dict) else {},
                "terminal": {
                    "title": (
                        terminal.get("title", "GG//DOS FRONTIER")
                        if isinstance(terminal, dict)
                        else "GG//DOS FRONTIER"
                    ),
                    "prompt": (
                        terminal.get("prompt", ">")
                        if isinstance(terminal, dict)
                        else ">"
                    ),
                    "lines": (
                        list(terminal.get("lines", []))
                        if isinstance(terminal, dict)
                        and isinstance(terminal.get("lines"), list)
                        else []
                    ),
                },
                "shared_contract": str(fallback.get("shared_contract", "")),
                "policy": str(fallback.get("policy", "")),
            },
        }
        # The full snapshot just paid for this frame.  Keep it so the next
        # compact tick does not raycast the same pose again.
        if isinstance(frame, dict) and frame.get("glyphs"):
            self._dos_live_frame = frame
            self._dos_live_frame_at = time.perf_counter()
            self._dos_live_motion = self._dos_motion_signature_locked(compact_rows)
        self._render_snapshot_signature = self._render_structure_signature_locked()

    def _render_snapshot_from_cache_locked(self) -> dict[str, Any]:
        """Refresh only dynamic render fields from a stable render template."""
        cache = self._render_snapshot_cache or {}
        cached_rows = cache.get("entities", [])
        cached_by_id = {
            str(row.get("id", "")): row
            for row in cached_rows
            if isinstance(row, dict) and row.get("id")
        }
        rows = [dict(row) for row in cached_rows]
        by_id = {
            str(row.get("id", "")): row
            for row in rows
            if isinstance(row, dict) and row.get("id")
        }

        for index in self._active_entity_indices:
            row = by_id.get(f"e-{index:04d}")
            if row is None:
                continue
            horizontal_speed = math.hypot(self._vx[index], self._vz[index])
            character_like = self._kind[index] in {"PLAYER", "NPC", "ACTOR"}
            animation_view = (
                animation_contract.build_pose(
                    sim_time=self._sim_time,
                    horizontal_speed=horizontal_speed,
                    grounded=(self._grounded if index == 0 else True),
                    sprinting=(self._sprinting if index == 0 else False),
                    vertical_velocity=self._vy[index],
                    travelled_distance_m=(
                        self._locomotion_distance_m if index == 0 else None
                    ),
                    movement_mode=(self._movement_mode if index == 0 else "GROUND"),
                    vehicle_kind=(self._vehicle_kind if index == 0 else "NONE"),
                    jump_stage=(self._jump_count if index == 0 else 0),
                    double_jump_remaining_s=(
                        self._double_jump_pose_remaining_s if index == 0 else 0.0
                    ),
                    grappling=(self._grapple_anchor is not None if index == 0 else False),
                    stand_state=(self._stand_state if index == 0 else 0),
                )
                if character_like
                else None
            )
            action_clip = self._decorate_character_animation_locked(
                animation_view,
                "player" if index == 0 else self._npc_ids[index],
            ) if character_like else ""
            # The compact stream must carry the asset's current clip state as
            # well as the animation pose.  The full snapshot cached the
            # binding at the previous state (normally IDLE); leaving that
            # object untouched made a character that had entered WALK still
            # look like it had a ready authored clip.  QML would then hide
            # the stable preview while the imported asset had no matching
            # clip.  Rebind from the same authoritative catalog and stable
            # instance rank, without changing the loader identity fields.
            current_asset = row.get("asset")
            if character_like and isinstance(current_asset, dict):
                new_state = (
                    str(animation_view.get("locomotion", animation_view.get("state", "IDLE")))
                    if isinstance(animation_view, dict)
                    else "IDLE"
                )
                cached_row = cached_by_id.get(f"e-{index:04d}")
                cached_state = str(
                    (cached_row or {}).get("motion_state")
                    or row.get("motion_state")
                    or ""
                )
                cached_animation = (cached_row or {}).get("animation")
                cached_action = str(cached_animation.get("action", "")) if isinstance(cached_animation, dict) else ""
                if cached_state != new_state or cached_action != action_clip:
                    try:
                        instance_rank = int(current_asset.get("instance_rank", -1))
                    except (TypeError, ValueError):
                        instance_rank = -1
                    row["asset"] = assets_contract.entity_binding(
                        self._asset_catalog,
                        new_state,
                        animation_view.get("phase", 0.0)
                        if isinstance(animation_view, dict)
                        else 0.0,
                        instance_rank,
                        asset_role=(
                            self._npc_archetype[index]
                            if self._kind[index] == "NPC"
                            and self._npc_archetype[index]
                            in {"WANDERER", "GUARDIAN", "CRITTER"}
                            else (
                                "CROWD"
                                if self._kind[index] in {"NPC", "ACTOR"}
                                else "DEFAULT"
                            )
                        ),
                        clip_override=action_clip,
                    )
                    if index == 0:
                        row['asset']=character_creation.binding(self._character_creation,row['asset'],new_state,action_clip)
                    if cached_row is not None:
                        cached_row["asset"] = row["asset"]
                        cached_row["motion_state"] = new_state
                        # Remember the bound action as well as locomotion so
                        # expiration can restore Idle/Walk on the compact path.
                        cached_row["animation"] = dict(animation_view or {})
            distance = math.sqrt(
                (self._x[index] - self._x[0]) ** 2
                + (self._y[index] - self._y[0]) ** 2
                + (self._z[index] - self._z[0]) ** 2
            )
            row.update(
                {
                    "x": _round(self._x[index]),
                    "y": _round(self._y[index]),
                    "z": _round(self._z[index]),
                    "yaw": _round(self._yaw[index], 4),
                    "pitch": _round(self._pitch[index], 3),
                    "roll": _round(self._roll[index], 3),
                    "speed": _round(horizontal_speed, 3),
                    "vehicle": self._vehicle_kind if index == 0 else "NONE",
                    # Keep the avatar visible in the skiff; its fixed offset
                    # places the feet inside the hull while the camera still
                    # follows the same third-person character anchor.
                    "hidden": False,
                    "motion_state": (
                        str(animation_view.get("locomotion", animation_view.get("state", "IDLE")))
                        if isinstance(animation_view, dict)
                        else "STATIC"
                    ),
                    "animation": animation_view,
                    "cell_key": world.cell_key(
                        world.chunk_coord(self._x[index]),
                        world.chunk_coord(self._z[index]),
                    ),
                    "lod": world.lod_tier_for_screen_error(
                        64.0 / max(1.0, distance * distance)
                    ),
                    "cast": (
                        self._npc_archetype[index]
                        if self._kind[index] == "NPC"
                        else ("PLAYER" if index == 0 else "")
                    ),
                }
            )
            if index == 0:
                previous_assets = {
                    str(item.get("instance_id", "")): item.get("asset", {})
                    for item in row.get("equipment", [])
                    if isinstance(item, dict)
                }
                equipment_rows: list[dict[str, Any]] = []
                for item in self._item_instances.values():
                    if (
                        not isinstance(item, dict)
                        or str(item.get("location")) != "EQUIPPED"
                        or str(item.get("owner_id")) != "player"
                    ):
                        continue
                    item_view = item_state.instance_view(
                        self._item_catalog,
                        item,
                        sim_time=self._sim_time,
                    )
                    instance_id = str(item_view.get("instance_id", ""))
                    item_view["asset"] = previous_assets.get(instance_id, {})
                    equipment_rows.append(
                        self._compact_render_item_view(self._equipment_visual_locked(item_view))
                    )
                    if len(equipment_rows) >= item_state.MAX_EQUIPPED_ITEMS:
                        break
                row["equipment"] = equipment_rows

        ambient_rows = life_contract.proxy_rows(
            self._life_spawns,
            self._sim_time,
            player_x=self._x[0],
            player_z=self._z[0],
            terrain_height=self._terrain_height_locked,
            render_radius_m=life_contract.RENDER_RADIUS_M,
        )
        for ambient_row in ambient_rows:
            if not isinstance(ambient_row, dict):
                continue
            row = by_id.get(str(ambient_row.get("id", "")))
            if row is None:
                continue
            x = float(ambient_row.get("x", 0.0))
            z = float(ambient_row.get("z", 0.0))
            current_asset = row.get("asset")
            ambient_animation = ambient_row.get("animation")
            ambient_id = str(ambient_row.get("id", ""))
            if isinstance(current_asset, dict):
                new_state = (
                    str(ambient_animation.get("locomotion", ambient_animation.get("state", "IDLE")))
                    if isinstance(ambient_animation, dict)
                    else "IDLE"
                )
                cached_row = cached_by_id.get(ambient_id)
                cached_state = str(
                    (cached_row or {}).get("motion_state")
                    or row.get("motion_state")
                    or ""
                )
                if cached_state != new_state:
                    try:
                        instance_rank = int(current_asset.get("instance_rank", -1))
                    except (TypeError, ValueError):
                        instance_rank = -1
                    row["asset"] = assets_contract.entity_binding(
                        self._asset_catalog,
                        new_state,
                        ambient_animation.get("phase", 0.0)
                        if isinstance(ambient_animation, dict)
                        else 0.0,
                        instance_rank,
                        asset_role="CROWD",
                    )
                    if cached_row is not None:
                        cached_row["asset"] = row["asset"]
                        cached_row["motion_state"] = new_state
            row.update(
                {
                    "x": ambient_row.get("x", 0.0),
                    "y": ambient_row.get("y", 0.0),
                    "z": ambient_row.get("z", 0.0),
                    "yaw": ambient_row.get("yaw", 0.0),
                    "speed": ambient_row.get("speed", 0.0),
                    "motion_state": ambient_row.get("motion_state", "IDLE"),
                    "animation": ambient_row.get("animation"),
                    "hidden": ambient_row.get("hidden", False),
                    "cell_key": world.cell_key(
                        world.chunk_coord(x), world.chunk_coord(z)
                    ),
                    "lod": world.lod_tier_for_screen_error(
                        64.0 / max(
                            1.0,
                            math.hypot(x - self._x[0], z - self._z[0]) ** 2,
                        )
                    ),
                }
            )

        for regional_row in self._world_people_rows_locked():
            row=by_id.get(regional_row['id'])
            if row is not None:
                row.update({key:regional_row[key] for key in ('x','y','z','yaw','speed','motion_state','animation','hidden','cell_key','lod','asset')})

        for instance_id in sorted(self._item_instances):
            instance = self._item_instances[instance_id]
            if (
                not isinstance(instance, dict)
                or str(instance.get("location")) != "GROUND"
                or not self._instance_item_visible_locked(instance)
            ):
                continue
            row = by_id.get(f"item-{instance_id}")
            if row is None:
                continue
            position = instance.get("position")
            position = position if isinstance(position, dict) else {}
            item_x = _clamp(position.get("x"), -1000000.0, 1000000.0)
            item_z = _clamp(position.get("z"), -1000000.0, 1000000.0)
            item_view = item_state.render_binding(
                self._item_catalog,
                instance,
                sim_time=self._sim_time,
            )
            previous_item = row.get("item")
            item_view["asset"] = (
                previous_item.get("asset", {})
                if isinstance(previous_item, dict)
                else {}
            )
            item_distance = math.sqrt(
                (item_x - self._x[0]) ** 2
                + (
                    self._terrain_height_locked(item_x, item_z) - self._y[0]
                ) ** 2
                + (item_z - self._z[0]) ** 2
            )
            row.update(
                {
                    "x": _round(item_x),
                    "y": _round(self._terrain_height_locked(item_x, item_z)),
                    "z": _round(item_z),
                    "item": self._compact_render_item_view(item_view),
                    "color": str(
                        item_view.get(
                            "visual", {}
                        ).get(
                            "base_color",
                            instance.get("rarity_color", "#d6d6d6"),
                        )
                    ) if isinstance(item_view.get("visual"), dict) else str(
                        instance.get("rarity_color", "#d6d6d6")
                    ),
                    "cell_key": world.cell_key(
                        world.chunk_coord(item_x), world.chunk_coord(item_z)
                    ),
                    "lod": world.lod_tier_for_screen_error(
                        64.0 / max(1.0, item_distance * item_distance)
                    ),
                }
            )

        entity_lod_counts: dict[str, int] = {}
        for row in rows:
            tier = str(row.get("lod", "ORBIT"))
            entity_lod_counts[tier] = entity_lod_counts.get(tier, 0) + 1

        render_policy = render_contract.PROFILES.get(
            self._render_profile,
            render_contract.PROFILES["BALANCED"],
        )
        particle_limit = min(
            RENDER_PARTICLE_LIMIT,
            int(render_policy["max_visible_particles"]),
        )
        particles: list[dict[str, Any]] = []
        for index in self._active_particle_indices:
            if self._plife[index] <= 0.0:
                continue
            point=self._ride_particle_world_locked(index)
            particles.append(
                {
                    "x": _round(point[0]),
                    "y": _round(point[1]),
                    "z": _round(point[2]),
                    "life": _round(self._plife[index]),
                    "color": self._pcolor[index],
                }
            )
            if len(particles) >= particle_limit:
                break

        speed = math.sqrt(
            self._vx[0] * self._vx[0]
            + self._vy[0] * self._vy[0]
            + self._vz[0] * self._vz[0]
        )
        facing = controller.character_basis(self._yaw[0])
        right_x, right_z = facing["right"]
        lateral = abs(right_x * self._vx[0] + right_z * self._vz[0])
        surface=self._player_surface_locked();surface_height=surface['height_m'];water_depth=surface['water_depth_m'];medium=surface['medium']
        mobility_view = mobility_contract.build_view(
            x=self._x[0],
            z=self._z[0],
            time_s=self._sim_time,
            movement_mode=self._movement_mode,
            vehicle_kind=self._vehicle_kind,
            water_depth=water_depth,
            speed=speed,
        )
        grapple_view = self._grapple_view_locked()
        player = dict(cache.get("player", {}))
        player['client_controls']=self._client_controls_view_locked()
        player['world_map']=self._instance_map_descriptor_locked()
        player['ride_frame']=self._ride_view_locked()
        player.pop('engine_world',None)
        if getattr(self,'_engine_world',None) is not None:player['engine_world']=self._engine_world.environment(self._x[0],self._y[0],self._z[0])
        player.update(
            {
                "x": _round(self._x[0]),
                "y": _round(self._y[0]),
                "z": _round(self._z[0]),
                "yaw": _round(self._yaw[0], 4),
                "speed": _round(speed, 2),
                "drift": _round(lateral, 2),
                "boost": bool(self._input.get("boost")),
                "grounded": self._grounded,
                "jump_stage": self._jump_count,
                "grapple": grapple_view,
                # Unrounded. The sea shader and this pose are one sample;
                # a rounded clock puts the picture on a later wave.
                "time_s": self._sim_time,
                "sprinting": self._sprinting,
                "movement_mode": self._movement_mode,
                "vehicle": self._vehicle_kind,
                "mobility": mobility_view,
                "cell_key": world.cell_key(
                    world.chunk_coord(self._x[0]),
                    world.chunk_coord(self._z[0]),
                ),
                "medium": medium,
                "surface_height": round(surface_height, 3),
                "biome": surface['biome'],
                "last_ability": self._last_ability,
                "last_ability_time": self._last_ability_time,
                "xp_visual": self._last_xp_visual,
            }
        )
        render_view = dict(cache.get("render_meta", {}))
        visibility = render_view.get("visibility")
        visibility = dict(visibility) if isinstance(visibility, dict) else {}
        visibility["visible_instances"] = len(rows)
        visibility["visible_particles"] = len(particles)
        visibility["entity_lod_counts"] = entity_lod_counts
        render_view["visibility"] = visibility
        render_view["entities"] = rows
        render_view["particles"] = particles
        render_view["draw_calls"] = (
            0
            if self._presentation_mode == render_contract.DOS_2D
            else None
        )
        if self._presentation_mode == render_contract.DOS_2D:
            render_view["fallback"] = self._live_dos_fallback_locked(rows)
        render_view["update_hz"] = (
            STRESS_RENDER_UPDATE_HZ if self._stress else RENDER_UPDATE_HZ
        )
        simulation_view = {
            "fixed_hz": FIXED_HZ,
            "dt_ms": round(FIXED_DT * 1000.0, 4),
            "tick": self._tick,
            "time_s": _round(self._sim_time, 2),
            "last_tick_ms": _round(self._last_tick_ms, 4),
            "max_tick_ms": _round(self._max_tick_ms, 4),
            "active_entities": self._entity_count,
            "entity_capacity": MAX_ENTITIES,
            "active_npcs": sum(
                1
                for index in self._npc_indices
                if self._alive[index]
            ),
            "active_particles": self._particle_count,
            "particle_capacity": MAX_PARTICLES,
            "render_entity_count": len(rows),
            "render_particle_count": len(particles),
            "frame_budget_ms": round(1000.0 / 60.0, 4),
            "allocation_policy": "BOUNDED_POOLS_NO_PER_TICK_GROWTH",
        }
        return {
            "schema": "gg.game-engine.render-snapshot.v1",
            "state": (
                "RUNNING"
                if self._running
                else ("PAUSED" if self._tick > 0 else "IDLE")
            ),
            "stress": self._stress,
            "player": player,
            "simulation": simulation_view,
            "rigid_physics": self._rigid_physics.frame(),
            "render": render_view,
            "fauna": self._fauna_view_locked(),
            "ecology": self._ecology_view_locked(),
            "nature": self._nature_view_locked(),
            "targeting": self._target_view_locked(),
            "actions": self._action_view_locked(),
            "firearms":self._firearms_view_locked(),
            "combat_live": {"resource":self._resource,"resource_capacity":100,"cooldowns":dict(self._ability_cooldowns),
                "profile":self._player_combat_profile_locked(),
                "player":dict(self._combat_state.get("actors",{}).get("player",{}))},
        }

    def render_snapshot_locked(self) -> dict[str, Any]:
        """Return the bounded 60 Hz render stream without rebuilding UI state."""
        signature = self._render_structure_signature_locked()
        if (
            self._render_snapshot_cache is None
            or self._render_snapshot_signature is None
            or signature[-1] != self._render_snapshot_signature[-1]
        ):
            # Initial/environment changes still refresh the complete terrain
            # contract. Ordinary entity/item changes never pay that cost.
            self.snapshot_locked()
        elif signature != self._render_snapshot_signature:
            self._refresh_render_entities_locked(signature)
        return self._render_snapshot_from_cache_locked()

    def _refresh_render_entities_locked(self, signature: tuple[Any, ...]) -> None:
        """Replace only scene templates after loot or population changes."""
        previous_signature = self._render_snapshot_signature
        items_changed = signature[1] != previous_signature[1]
        identities_changed = (
            tuple(row[:3] for row in signature[0])
            != tuple(row[:3] for row in previous_signature[0])
        )
        if items_changed:
            self._ensure_inventory_slots_locked()
        if items_changed or identities_changed:
            # Preserve the state preparation previously done by a full
            # snapshot, without constructing its terrain/navigation views.
            self._ensure_combat_actors_locked()
            self._sync_npc_combat_presence_locked()
        rows, item_views, ambient_rows, item_rank = self._render_entity_rows_locked(include_identity=False)
        cache = dict(self._render_snapshot_cache)
        cache["entities"] = [self._compact_render_entity_row(row) for row in rows]
        counts = {key: 0 for key in ("ground", "containers", "inventory", "equipment")}
        for item in self._instance_visible_item_rows_locked():
            if not isinstance(item, dict):
                continue
            if item.get("location") == "GROUND":
                counts["ground"] += 1
                counts["containers"] += item.get("kind") == "CONTAINER"
            elif item.get("owner_id") == "player":
                if item.get("location") == "INVENTORY":
                    counts["inventory"] += 1
                elif item.get("location") == "EQUIPPED":
                    counts["equipment"] += 1
        counts["inventory"] = min(counts["inventory"], item_state.MAX_INVENTORY_SLOTS)
        counts["equipment"] = min(counts["equipment"], item_state.MAX_EQUIPPED_ITEMS)
        meta = dict(cache["render_meta"])
        meta.update(self._render_instance_metadata_locked(rows, item_views, item_rank, counts))
        cache["render_meta"] = meta
        self._render_snapshot_cache = cache
        self._render_snapshot_signature = signature
        if self._ui_snapshot_base is not None:
            # Population promotion happens on the simulator, without a user
            # command/full snapshot. Keep its small inspector summary current.
            ui = dict(self._ui_snapshot_base)
            if items_changed:
                items = item_state.build_state_view(
                    self._item_catalog, self._instance_visible_item_rows_locked(),
                    player_x=self._x[0], player_z=self._z[0], sim_time=self._sim_time,
                    last_interaction=self._last_item_interaction,
                )
                ui["items"] = self._ui_status_from_snapshot({"items": items})["items"]
            if signature[2:4] != previous_signature[2:4]:
                living = dict(ui.get("living_world", {}))
                living.update(promoted_ids=sorted(self._promoted_life_ids),
                              promoted_count=len(self._promoted_life_ids),
                              ambient_count=len(self._life_spawns),
                              last_promotion_s=round(self._last_population_promotion_s, 3))
                ui["living_world"] = living
                life = life_contract.build_view(ambient_rows, self._sim_time)
                ui["life"] = self._ui_status_from_snapshot({"life": life})["life"]
            if identities_changed:
                npc = dict(ui.get("npc", {}))
                active_npcs = [i for i in self._npc_indices if self._alive[i]]
                npc["active"] = len(active_npcs)
                npc["agents"] = [self._compact_ui_npc_row({
                    "id": self._npc_ids[i], "entity_id": f"e-{i:04d}",
                    "archetype": self._npc_archetype[i], "state": self._npc_state[i],
                    "x": _round(self._x[i]), "y": _round(self._y[i]), "z": _round(self._z[i]),
                    "yaw": _round(self._yaw[i], 4), "speed": _round(math.hypot(self._vx[i], self._vz[i]), 2),
                    "stimulus": self._npc_stimulus[i], "line_of_sight": self._npc_line_of_sight[i],
                    "path_status": self._npc_path_status[i], "path_nodes": len(self._npc_path[i]),
                    "path_index": self._npc_path_index[i],
                    "combat": copy.deepcopy(self._combat_state.get("actors", {}).get(self._npc_ids[i], {})),
                    "individual": identity_contract.view(self._individual_state, self._npc_ids[i]),
                }) for i in active_npcs[:4]]
                ui["npc"] = npc
            self._ui_snapshot_base = ui

    def _render_entity_rows_locked(self, *, include_identity: bool = True):
        """Build scene rows without terrain, navigation or inspector catalogues."""
        self._world_population.select(self._sim_time,self._x[0],self._z[0])
        policy = render_contract.PROFILES.get(self._render_profile, render_contract.PROFILES["BALANCED"])
        entity_render_limit = min(RENDER_ENTITY_LIMIT, int(policy["max_visible_instances"]))
        entity_rows: list[dict[str, Any]] = []
        item_render_views: list[dict[str, Any]] = []
        authored_item_rank = 0

        def bind_item_render_view(view: dict[str, Any]) -> dict[str, Any]:
            """Attach an authored static item binding without touching simulation."""
            nonlocal authored_item_rank
            visual = view.get("visual", {})
            asset_id = visual.get("asset_id") if isinstance(visual, dict) else ""
            binding = assets_contract.item_binding(
                self._asset_catalog,
                asset_id,
                authored_item_rank,
                view.get("kind", "ITEM"),
                appearance_index=item_state.item_appearance_index(view.get('instance_id',view.get('id',asset_id))),
            )
            view["asset"] = binding
            item_render_views.append(view)
            if binding.get("mode") == "AUTHORED_STATIC":
                authored_item_rank += 1
            return view

        authored_instance_rank = 0
        for index in self._active_entity_indices:
            distance = math.sqrt(
                (self._x[index] - self._x[0]) ** 2
                + (self._y[index] - self._y[0]) ** 2
                + (self._z[index] - self._z[0]) ** 2
            )
            projected_error = 64.0 / max(1.0, distance * distance)
            entity_cell_x = world.chunk_coord(self._x[index])
            entity_cell_z = world.chunk_coord(self._z[index])
            horizontal_speed = math.hypot(self._vx[index], self._vz[index])
            character_like = self._kind[index] in {"PLAYER", "NPC", "ACTOR"}
            animation_view = (
                animation_contract.build_pose(
                    sim_time=self._sim_time,
                    horizontal_speed=horizontal_speed,
                    grounded=(self._grounded if index == 0 else True),
                    sprinting=(self._sprinting if index == 0 else False),
                    vertical_velocity=self._vy[index],
                    travelled_distance_m=(
                        self._locomotion_distance_m if index == 0 else None
                    ),
                    movement_mode=(self._movement_mode if index == 0 else "GROUND"),
                    vehicle_kind=(self._vehicle_kind if index == 0 else "NONE"),
                    jump_stage=(self._jump_count if index == 0 else 0),
                    double_jump_remaining_s=(
                        self._double_jump_pose_remaining_s if index == 0 else 0.0
                    ),
                    grappling=(self._grapple_anchor is not None if index == 0 else False),
                    stand_state=(self._stand_state if index == 0 else 0),
                )
                if character_like
                else None
            )
            action_clip = self._decorate_character_animation_locked(
                animation_view,
                "player" if index == 0 else self._npc_ids[index],
            ) if character_like else ""
            asset_view = (
                assets_contract.entity_binding(
                    self._asset_catalog,
                    animation_view.get(
                        "locomotion",
                        animation_view.get("state", "IDLE"),
                    ),
                    animation_view.get("phase", 0.0),
                    authored_instance_rank,
                    asset_role=(
                        self._npc_archetype[index]
                        if self._kind[index] == "NPC"
                        and self._npc_archetype[index]
                        in {"WANDERER", "GUARDIAN", "CRITTER"}
                        else (
                            "CROWD"
                            if self._kind[index] in {"NPC", "ACTOR"}
                            else "DEFAULT"
                        )
                    ),
                    clip_override=action_clip,
                )
                if isinstance(animation_view, dict)
                else None
            )
            if index == 0 and isinstance(asset_view,dict):
                asset_view=character_creation.binding(self._character_creation,asset_view,
                    animation_view.get('locomotion',animation_view.get('state','IDLE')),action_clip)
            if character_like:
                authored_instance_rank += 1
            world_asset_view = (
                assets_contract.world_prop_asset(
                    self._kind[index],
                    f"e-{index:04d}",
                )
                if not character_like
                else None
            )
            equipment_rows: list[dict[str, Any]] = []
            if index == 0:
                for item in self._item_instances.values():
                    if (
                        not isinstance(item, dict)
                        or str(item.get("location")) != "EQUIPPED"
                        or str(item.get("owner_id")) != "player"
                    ):
                        continue
                    equipment_rows.append(
                        self._equipment_visual_locked(bind_item_render_view(
                            item_state.instance_view(
                                self._item_catalog,
                                item,
                                sim_time=self._sim_time,
                            )
                        ))
                    )
                    if len(equipment_rows) >= item_state.MAX_EQUIPPED_ITEMS:
                        break
            individual = None
            if self._kind[index] == "NPC":
                if include_identity:
                    individual = identity_contract.view(self._individual_state, self._npc_ids[index])
                else:
                    person = self._individual_state.get("individuals", {}).get(self._npc_ids[index])
                    if isinstance(person, dict):
                        individual = {"id": self._npc_ids[index]}
                        if isinstance(person.get("name"), str):
                            individual["name"] = person["name"]
            entity_rows.append(
                {
                    "id": f"e-{index:04d}",
                    "kind": self._kind[index],
                    "cast": (
                        self._npc_archetype[index]
                        if self._kind[index] == "NPC"
                        else ("PLAYER" if index == 0 else "")
                    ),
                    "x": _round(self._x[index]),
                    "y": _round(self._y[index]),
                    "z": _round(self._z[index]),
                    "yaw": _round(self._yaw[index], 4),
                    "pitch": _round(self._pitch[index], 3),
                    "roll": _round(self._roll[index], 3),
                    "sx": _round(self._sx[index]),
                    "sy": _round(self._sy[index]),
                    "sz": _round(self._sz[index]),
                    "color": self._color[index],
                    "speed": _round(horizontal_speed, 3),
                    "vehicle": self._vehicle_kind if index == 0 else "NONE",
                    "hidden": False,
                    "motion_state": (
                        str(animation_view.get("locomotion", animation_view.get("state", "IDLE")))
                        if isinstance(animation_view, dict)
                        else "STATIC"
                    ),
                    "animation": animation_view,
                    "asset": asset_view if character_like else world_asset_view,
                    "equipment": equipment_rows,
                    "individual": individual,
                    "item": None,
                    "cell_key": world.cell_key(entity_cell_x, entity_cell_z),
                    "lod": world.lod_tier_for_screen_error(projected_error),
                }
            )
            if len(entity_rows) >= entity_render_limit:
                break

        self._append_corpse_render_locked(entity_rows,entity_render_limit)
        # World items are visual instances, not physics actors.  They stay out
        # of the entity pool so adding loot cannot change the stable movement,
        # collision or NPC capacities.  Their item state remains authoritative
        # in the same snapshot and the QML delegate renders the 3D binding.
        ambient_life_rows = self._ambient_life_rows_locked(include_identity=include_identity)
        for ambient_row in ambient_life_rows:
            if len(entity_rows) >= entity_render_limit:
                break
            if (
                not isinstance(ambient_row, dict)
            ):
                continue
            if not include_identity:
                person = self._individual_state.get("individuals", {}).get(ambient_row.get("id"))
                if isinstance(person, dict):
                    ambient_row["individual"] = {"id": ambient_row["id"]}
                    if isinstance(person.get("name"), str):
                        ambient_row["individual"]["name"] = person["name"]
            ambient_animation = ambient_row.get("animation")
            if str(ambient_row.get("kind", "")) == "ACTOR":
                # Ambient residents use the same bounded character asset seam
                # as pooled actors.  Their life simulation remains a proxy,
                # but their visible model is still the one authored low-poly
                # model instead of a second detailed preview body.
                ambient_row["asset"] = assets_contract.entity_binding(
                    self._asset_catalog,
                    (ambient_animation or {}).get("locomotion", (ambient_animation or {}).get("state", "IDLE")),
                    (ambient_animation or {}).get("phase", 0.0),
                    authored_instance_rank,
                    asset_role="CROWD",
                )
                authored_instance_rank += 1
            entity_rows.append(ambient_row)

        for row in self._world_people_rows_locked():
            if len(entity_rows)>=entity_render_limit:break
            entity_rows.append(row)

        for instance_id in sorted(self._item_instances):
            if len(entity_rows) >= entity_render_limit:
                break
            instance = self._item_instances[instance_id]
            if not isinstance(instance, dict) or str(instance.get("location")) != "GROUND" or not self._instance_item_visible_locked(instance):
                continue
            position = instance.get("position", {})
            try:
                item_x = float(position.get("x", 0.0))
                item_z = float(position.get("z", 0.0))
            except (TypeError, ValueError):
                continue
            item_binding = bind_item_render_view(
                item_state.render_binding(
                    self._item_catalog,
                    instance,
                    sim_time=self._sim_time,
                )
            )
            visual = item_binding.get("visual", {})
            item_distance = math.sqrt(
                (item_x - self._x[0]) ** 2
                + (self._terrain_height_locked(item_x, item_z) - self._y[0]) ** 2
                + (item_z - self._z[0]) ** 2
            )
            item_cell_x = world.chunk_coord(item_x)
            item_cell_z = world.chunk_coord(item_z)
            entity_rows.append(
                {
                    "id": f"item-{instance_id}",
                    "kind": "CHEST" if str(instance.get("kind")) == "CONTAINER" else "GROUND_ITEM",
                    "x": _round(item_x),
                    "y": _round(self._terrain_height_locked(item_x, item_z)),
                    "z": _round(item_z),
                    "yaw": 0.0,
                    "sx": 1.0,
                    "sy": 1.0,
                    "sz": 1.0,
                    "color": str(visual.get("base_color", instance.get("rarity_color", "#d6d6d6"))),
                    "speed": 0.0,
                    "motion_state": "STATIC",
                    "animation": None,
                    "asset": None,
                    "equipment": [],
                    "item": item_binding,
                    "cell_key": world.cell_key(item_cell_x, item_cell_z),
                    "lod": world.lod_tier_for_screen_error(
                        64.0 / max(1.0, item_distance * item_distance)
                    ),
                }
            )

        return entity_rows, item_render_views, ambient_life_rows, authored_item_rank

    def _render_instance_metadata_locked(self, entity_rows, item_render_views, authored_item_rank, item_counts):
        """The same bounded scene counters for full and compact publications."""
        return {
            "asset_instances": {
                "authored_requested": sum(
                    1
                    for row in entity_rows
                    if str(row.get("kind", "")) in {
                        "PLAYER", "NPC", "ACTOR"
                    }
                    if isinstance(row.get("asset"), dict)
                    and row["asset"].get("mode") in {
                        "AUTHORED_SKINNED",
                        "AUTHORED_NODE_ANIMATED",
                    }
                ),
                "procedural_requested": sum(
                    1
                    for row in entity_rows
                    if str(row.get("kind", "")) in {
                        "PLAYER", "NPC", "ACTOR"
                    }
                    if isinstance(row.get("asset"), dict)
                    and row["asset"].get("mode")
                    == assets_contract.PROCEDURAL_CHARACTER_MODE
                ),
                "preview_fallback": sum(
                    1
                    for row in entity_rows
                    if str(row.get("kind", "")) in {
                        "PLAYER", "NPC", "ACTOR"
                    }
                    if isinstance(row.get("asset"), dict)
                    and row["asset"].get("mode") not in {
                        "AUTHORED_SKINNED",
                        "AUTHORED_NODE_ANIMATED",
                        assets_contract.PROCEDURAL_CHARACTER_MODE,
                    }
                ),
                "budget": assets_contract.MAX_AUTHORED_INSTANCES,
            },
            "item_instances": {
                "ground": item_counts["ground"],
                "containers": item_counts["containers"],
                "inventory": item_counts["inventory"],
                "equipped": item_counts["equipment"],
                "budget": item_state.MAX_WORLD_INSTANCES,
            },
            "item_asset_instances": {
                "authored_requested": authored_item_rank,
                "procedural_requested": sum(
                    1
                    for view in item_render_views
                    if isinstance(view.get("asset"), dict)
                    and view["asset"].get("mode")
                    == assets_contract.PROCEDURAL_ASSET_MODE
                ),
                "primitive_fallback": sum(
                    1
                    for view in item_render_views
                    if isinstance(view.get("asset"), dict)
                    and view["asset"].get("mode") not in {
                        "AUTHORED_STATIC",
                        assets_contract.PROCEDURAL_ASSET_MODE,
                    }
                ),
                "budget": assets_contract.MAX_AUTHORED_ITEM_INSTANCES,
            },
            "world_asset_instances": {
                "native_requested": sum(
                    1
                    for row in entity_rows
                    if str(row.get("kind", "")) not in {
                        "PLAYER",
                        "NPC",
                        "ACTOR",
                        "GROUND_ITEM",
                        "CHEST",
                    }
                ),
                "primitive_fallback": 0,
                "budget": assets_contract.PROCEDURAL_ASSET_MAX_FAMILIES,
            },
            "ambient_life": {
                "visible": sum(
                    1
                    for row in entity_rows
                    if str(row.get("id", "")).startswith("ambient-")
                ),
                "budget": life_contract.MAX_PROXIES,
                "simulation": "RENDER_ONLY_DETERMINISTIC_SCHEDULES",
            },
        }

    def snapshot_locked(self) -> dict[str, Any]:
        self._ensure_inventory_slots_locked()
        snapshot_started = time.perf_counter()
        self._ensure_combat_actors_locked()
        self._sync_npc_combat_presence_locked()
        render_policy = render_contract.PROFILES.get(
            self._render_profile,
            render_contract.PROFILES["BALANCED"],
        )
        particle_render_limit = min(
            RENDER_PARTICLE_LIMIT,
            int(render_policy["max_visible_particles"]),
        )
        if self._running:
            state = "RUNNING"
        elif self._tick > 0:
            state = "PAUSED"
        else:
            state = "IDLE"

        entity_rows, item_render_views, ambient_life_rows, authored_item_rank = self._render_entity_rows_locked()

        entity_lod_counts: dict[str, int] = {}
        for row in entity_rows:
            tier = str(row.get("lod", "ORBIT"))
            entity_lod_counts[tier] = entity_lod_counts.get(tier, 0) + 1

        particle_rows: list[dict[str, Any]] = []
        for index in self._active_particle_indices:
            if self._plife[index] <= 0.0:
                continue
            point=self._ride_particle_world_locked(index)
            particle_rows.append(
                {
                    "x": _round(point[0]),
                    "y": _round(point[1]),
                    "z": _round(point[2]),
                    "life": _round(self._plife[index]),
                    "color": self._pcolor[index],
                }
            )
            if len(particle_rows) >= particle_render_limit:
                break

        speed = math.sqrt(
            self._vx[0] * self._vx[0]
            + self._vy[0] * self._vy[0]
            + self._vz[0] * self._vz[0]
        )
        facing = controller.character_basis(self._yaw[0])
        right_x, right_z = facing["right"]
        lateral = abs(right_x * self._vx[0] + right_z * self._vz[0])
        physics_view = physics.build_runtime_view(
            speed=speed,
            movement_mode=self._movement_mode,
            active_entities=self._entity_count,
            active_particles=self._particle_count,
            resource=self._resource,
        )
        physics_view["rigid_body"] = self._rigid_physics.status()
        render_policy = render_contract.PROFILES.get(
            self._render_profile,
            render_contract.PROFILES["PS2_CLASSIC"],
        )
        # Keep the ordinary third-person preview to a PS2-scale nearby scene.
        # Extend the ring only when the editor camera zooms out; the gameplay
        # interest set, simulation and island surface remain untouched.
        render_radius = min(
            int(render_policy.get("max_render_radius", world.DEFAULT_RENDER_RADIUS)),
            max(4, int(math.ceil(self._camera_distance / CHUNK_SIZE)) + 2),
        )
        world_view = world.build_world_view(
            (self._x[0], self._y[0], self._z[0]),
            movement_mode=self._movement_mode,
            camera_yaw=self._camera_yaw,
            camera_pitch=self._camera_pitch,
            camera_distance=self._camera_distance,
            interest_radius=world.DEFAULT_INTEREST_RADIUS,
            render_radius=render_radius,
        )
        streaming_view = world_view["streaming"]
        chunks = list(streaming_view["loaded_cells"][:MAX_CHUNKS])
        render_chunks = list(
            streaming_view.get("render_cells", chunks)[:MAX_RENDER_CHUNKS]
        )
        terrain_view = terrain_contract.build_terrain_view(
            render_chunks,
            (self._x[0], self._y[0], self._z[0]),
            self._movement_mode,
            world_seed=WORLD_SEED,
            overrides=self._terrain_overrides,
            cell_cache=self._terrain_cell_cache,
        )
        if getattr(self,'_engine_world',None) is not None:
            terrain_view['player_surface']={**terrain_view['player_surface'],**self._player_surface_locked()}
        navigation_tiles = self._navigation_tiles_for_cells_locked(
            chunks,
            self._movement_mode,
        )
        navigation_view = nav_contract.navmesh_view_from_tiles(
            navigation_tiles,
            chunks,
            (self._x[0], self._y[0], self._z[0]),
            self._movement_mode,
        )
        npc_rows: list[dict[str, Any]] = []
        for index in self._npc_indices[: npc_contract.MAX_NPCS]:
            if not self._alive[index]:
                continue
            npc_individual_view = identity_contract.view(
                self._individual_state,
                self._npc_ids[index],
            )
            npc_combat_view = self._combat_state.get("actors", {}).get(self._npc_ids[index], {})
            npc_rows.append(
                {
                    "id": self._npc_ids[index] or f"npc-{index:04d}",
                    "entity_id": f"e-{index:04d}",
                    "archetype": self._npc_archetype[index],
                    "state": self._npc_state[index],
                    "x": _round(self._x[index]),
                    "y": _round(self._y[index]),
                    "z": _round(self._z[index]),
                    "yaw": _round(self._yaw[index], 4),
                    "home_x": _round(self._npc_home_x[index]),
                    "home_z": _round(self._npc_home_z[index]),
                    "target_x": _round(self._npc_target_x[index]),
                    "target_z": _round(self._npc_target_z[index]),
                    "speed": _round(math.hypot(self._vx[index], self._vz[index]), 2),
                    "perception_radius_m": _round(self._npc_perception_radius[index], 2),
                    "target_distance_m": _round(self._npc_target_distance[index], 2),
                    "state_time_s": _round(self._npc_state_time[index], 2),
                    "reason": self._npc_reason[index],
                    "stimulus": self._npc_stimulus[index],
                    "world_action": npc_individual_view.get("action", "WANDER"),
                    "world_target": npc_individual_view.get("target", {}),
                    "line_of_sight": self._npc_line_of_sight[index],
                    "last_seen_age_s": _round(self._npc_last_seen_age[index], 2),
                    "last_seen_x": _round(self._npc_last_seen_x[index]),
                    "last_seen_z": _round(self._npc_last_seen_z[index]),
                    "interaction_count": self._npc_interaction_count[index],
                    "combat": copy.deepcopy(npc_combat_view) if isinstance(npc_combat_view, dict) else {},
                    "path_status": self._npc_path_status[index],
                    "path_nodes": len(self._npc_path[index]),
                    "path_index": self._npc_path_index[index],
                    "individual": npc_individual_view,
                    "cell_key": world.cell_key(
                        world.chunk_coord(self._x[index]),
                        world.chunk_coord(self._z[index]),
                    ),
                }
            )
        interaction_target = npc_contract.nearest_interaction_target(
            npc_rows,
            self._x[0],
            self._z[0],
        )
        regional_target=self._regional_interaction_target_locked()
        if regional_target and (not interaction_target or regional_target['distance_m']<interaction_target['distance_m']):
            interaction_target=regional_target
        npc_view = npc_contract.build_view(
            npc_rows,
            interaction=interaction_target,
            last_interaction=self._npc_last_interaction,
        )
        item_view = item_state.build_state_view(
            self._item_catalog,
            self._instance_visible_item_rows_locked(),
            player_x=self._x[0],
            player_z=self._z[0],
            sim_time=self._sim_time,
            last_interaction=self._last_item_interaction,
        )
        item_view['equipment']=[self._tabard_equipment_visual_locked(row) for row in item_view['equipment']]
        ambient_life_view = life_contract.build_view(
            ambient_life_rows,
            self._sim_time,
        )
        active_people_ids = [
            self._npc_ids[index]
            for index in self._npc_indices
            if self._alive[index] and self._npc_ids[index]
        ]
        active_people_ids.extend(
            str(row.get("id", ""))
            for row in self._life_spawns
            if isinstance(row, dict) and row.get("id")
        )
        people_view = identity_contract.build_view(
            self._individual_state,
            active_people_ids,
        )
        dialogue_view = dialogue_contract.view(
            self._dialogue_state,
            self._regional_dialogue_catalog_locked(),
        )
        dialogue_view['accessible']=self._quest_contact_locked(dialogue_view.get('active',{}).get('npc_id',''))
        dialogue_view['gossip_hidden']=bool(getattr(self,'_engine_gossip_hidden',False))
        social_view = social_contract.view(
            self._social_state,
            active_people_ids,
        )
        world_events_view = world_events_contract.view(
            self._world_event_state,
            self._world_event_catalog,
        )
        living_world_view = {
            "schema": "gg.game-engine.living-world.v1",
            "promoted_ids": sorted(self._promoted_life_ids)[:MAX_POPULATION_PROMOTIONS],
            "promoted_count": len(self._promoted_life_ids),
            "ambient_count": len(self._life_spawns),
            "promotion_interval_s": POPULATION_PROMOTION_INTERVAL_S,
            "promotion_budget": MAX_POPULATION_PROMOTIONS,
            "last_promotion_s": round(self._last_population_promotion_s, 3),
            "policy": "AMBIENT_PROXY_TO_REAL_NPC_POOL_WITH_PERSISTED_BOUNDARY",
            "regional_population": self._world_population.view(),
        }
        fauna_view = self._fauna_view_locked()
        ecology_view = self._ecology_view_locked()
        snapshot_build_ms = (time.perf_counter() - snapshot_started) * 1000.0
        render_view = render_contract.build_render_view(
            self._render_profile,
            active_entities=self._entity_count,
            active_particles=self._particle_count,
            snapshot_build_ms=snapshot_build_ms,
            presentation_mode=self._presentation_mode,
            presentation_reason=self._presentation_reason,
        )
        event_journal_view = events_contract.view(self._event_journal, limit=24)
        dos_view = dos_contract.history_view(
            self._dos_history,
            self._last_dos_command,
        )
        vendor_presence: dict[str, dict[str, Any]] = {}
        vendor_needs: dict[str, dict[str, Any]] = {}
        identity_rows = self._individual_state.get("individuals", {})
        for vendor_id in sorted(self._vendor_catalog)[: economy_contract.MAX_VENDORS]:
            vendor = self._vendor_catalog.get(vendor_id)
            if not isinstance(vendor, dict):
                continue
            npc_id = str(vendor.get("npc_id", ""))
            person = identity_rows.get(npc_id) if isinstance(identity_rows, dict) else None
            vendor_needs[str(vendor_id)] = (
                copy.deepcopy(person.get("needs", {}))
                if isinstance(person, dict)
                else {}
            )
            npc_index = next(
                (
                    index
                    for index in self._npc_indices
                    if self._alive[index] and str(self._npc_ids[index]) == npc_id
                ),
                None,
            )
            if npc_index is None:
                vendor_presence[str(vendor_id)] = {
                    "npc_id": npc_id,
                    "available": False,
                    "reason": "NPC_UNAVAILABLE",
                }
                continue
            distance = math.hypot(
                self._x[npc_index] - self._x[0],
                self._z[npc_index] - self._z[0],
            )
            line_of_sight = self._npc_line_of_sight_locked(npc_index)
            vendor_presence[str(vendor_id)] = {
                "npc_id": npc_id,
                "distance_m": round(distance, 3),
                "line_of_sight": bool(line_of_sight),
                "available": bool(
                    distance <= economy_contract.INTERACTION_RADIUS_M
                    and line_of_sight
                    and self._combat_state.get('actors', {}).get(npc_id, {}).get('alive', True)
                    and self._combat_state.get('actors', {}).get('player', {}).get('alive', True)
                ),
                "radius_m": economy_contract.INTERACTION_RADIUS_M,
            }
        economy_view = economy_contract.build_view(
            self._economy_state,
            self._vendor_catalog,
            self._item_instances.values(),
            item_viewer=lambda row: item_state.instance_view(
                self._item_catalog,
                row,
                sim_time=self._sim_time,
            ),
            definition_lookup=lambda definition_id: item_state.definition(
                self._item_catalog,
                definition_id,
            ),
            presence=vendor_presence,
            vendor_needs=vendor_needs,
        )
        fallback_view = fallback_contract.build_view(
            entity_rows,
            terrain_view.get("cells", []),
            player_x=self._x[0],
            player_y=self._y[0],
            player_z=self._z[0],
            player_yaw=self._yaw[0],
            state=state,
            tick=self._tick,
            active_entities=self._entity_count,
            active_particles=self._particle_count,
            event_rows=event_journal_view["events"][-4:],
            command=dos_view["last"],
            equipment_rows=item_view.get("equipment", []),
            economy=economy_view,
            combat=combat_contract.view(self._combat_state),
            quests=quests_contract.view(self._quest_state, self._quest_catalog),
            factions=factions_contract.view(self._faction_state),
            dialogue=dialogue_view,
            social=social_view,
            world_events=world_events_view,
        )
        render_view.update(
            {
                "entities": entity_rows,
                "particles": particle_rows,
                "fallback": fallback_view,
                "draw_calls": (
                    0
                    if self._presentation_mode == render_contract.DOS_2D
                    else None
                ),
                # The scene is now native geometry first.  The authored path
                # is reported separately, while the bounded primitive path is
                # retained only for an older host without the geometry slots.
                "renderer": "QTQUICK3D_NATIVE_GEOMETRY",
                "authored_asset_renderer": (
                    "QTQUICK3D_RUNTIME_LOADER_PLUS_PROCEDURAL_GEOMETRY"
                ),
                **self._render_instance_metadata_locked(
                    entity_rows, item_render_views, authored_item_rank,
                    {key: len(item_view[key]) for key in ("ground", "containers", "inventory", "equipment")},
                ),
                "update_hz": (
                    STRESS_RENDER_UPDATE_HZ
                    if self._stress
                    else RENDER_UPDATE_HZ
                ),
            }
        )
        render_view["visibility"]["entity_lod_counts"] = entity_lod_counts
        network_view = mmo.build_network_view(
            world_view,
            sequence=self._network_seq,
            active_entities=self._entity_count,
            persistence_revision=self._persistence_revision,
            persistence_mode=getattr(self._state_store, 'mode', 'MEMORY_ONLY'),
        )
        cinematic_view = cinematic.build_view(
            self._cinematic_preset,
            movement_mode=self._movement_mode,
            camera_distance=self._camera_distance,
        )
        cinematic_view.update(self._opening_cinematic_view_locked())
        combat_view = combat_contract.view(self._combat_state)
        combat_view.update(
            {
                "ability_id": "ability.surge",
                "ability_name": self._content["abilities"]["ability.surge"]["name"],
                "resource": round(self._resource, 2),
                "resource_capacity": 100,
                "cooldowns": {
                    key: round(value, 3)
                    for key, value in self._ability_cooldowns.items()
                },
                "last_ability": self._last_ability,
                "last_status": self._last_ability_status,
                "last_result": copy.deepcopy(self._last_combat),
                "player_profile": self._player_combat_profile_locked(),
                "policy": "FIXED_STEP_DETERMINISTIC_DAMAGE_WITH_REAL_ACTOR_STATE",
            }
        )

        snapshot = {
            "schema": SCHEMA,
            "state": state,
            "mode": "LOCAL_PLAYGROUND",
            "stress": self._stress,
            "assets": self._asset_catalog,
            "character_creation": character_creation.view(self._character_creation),
            "items": item_view,
            "life": ambient_life_view,
            "living_world": living_world_view,
            "regional_population": self._world_population.view(),
            "fauna": fauna_view,
            "ecology": ecology_view,
            "nature": self._nature_view_locked(),
            "targeting": self._target_view_locked(),
            "actions": self._action_view_locked(),
            "firearms":self._firearms_view_locked(),
            "combat_live": {"resource":self._resource,"resource_capacity":100,"cooldowns":dict(self._ability_cooldowns),
                "profile":self._player_combat_profile_locked(),
                "player":dict(self._combat_state.get("actors",{}).get("player",{}))},
            "simulation": {
                "fixed_hz": FIXED_HZ,
                "dt_ms": round(FIXED_DT * 1000.0, 4),
                "tick": self._tick,
                "time_s": _round(self._sim_time, 2),
                "last_tick_ms": _round(self._last_tick_ms, 4),
                "max_tick_ms": _round(self._max_tick_ms, 4),
                "active_entities": self._entity_count,
                "entity_capacity": MAX_ENTITIES,
                "active_npcs": npc_view["active"],
                "active_particles": self._particle_count,
                "particle_capacity": MAX_PARTICLES,
                "render_entity_count": len(entity_rows),
                "render_particle_count": len(particle_rows),
                "frame_budget_ms": round(1000.0 / 60.0, 4),
                "allocation_policy": "BOUNDED_POOLS_NO_PER_TICK_GROWTH",
            },
            "player": {
                "name": getattr(self, '_local_character_name', 'Gold Goblin'),
                "client_controls": self._client_controls_view_locked(),
                "world_map": self._instance_map_descriptor_locked(),
                "ride_frame": self._ride_view_locked(),
                "x": _round(self._x[0]),
                "y": _round(self._y[0]),
                "z": _round(self._z[0]),
                "yaw": _round(self._yaw[0], 4),
                "speed": _round(speed, 2),
                "drift": _round(lateral, 2),
                "boost": bool(self._input.get("boost")),
                "grounded": self._grounded,
                "jump_stage": self._jump_count,
                "grapple": self._grapple_view_locked(),
                "time_s": self._sim_time,
                "sprinting": self._sprinting,
                "movement_mode": self._movement_mode,
                "vehicle": self._vehicle_kind,
                "mobility": mobility_contract.build_view(
                    x=self._x[0],
                    z=self._z[0],
                    time_s=self._sim_time,
                    movement_mode=self._movement_mode,
                    vehicle_kind=self._vehicle_kind,
                    water_depth=self._water_depth_locked(self._x[0], self._z[0]),
                    speed=speed,
                ),
                "cell_key": world_view["player_cell"]["key"],
                "medium": terrain_view["player_surface"]["medium"],
                "surface_height": terrain_view["player_surface"]["height_m"],
                "biome": planet_contract.biome_at(self._x[0], self._z[0], WORLD_SEED),
                "last_ability": self._last_ability,
                "last_ability_time": self._last_ability_time,
                "xp_visual": self._last_xp_visual,
            },
            "input": dict(self._input),
            "keybindings": input_contract.summary(self._keybindings),
            "addons": addons_contract.summary(self._addons),
            "controller": controller.build_view(
                camera_yaw=self._camera_yaw,
                camera_pitch=self._camera_pitch,
                camera_distance=self._camera_distance,
                grounded=self._grounded,
                sprinting=self._sprinting,
            ),
            "render": render_view,
            "terrain": terrain_view,
            "navigation": navigation_view,
            "terrain_editor": terrain_contract.summary(self._terrain_overrides),
            "npc": npc_view,
            "people": people_view,
            "gear": gear_contract.table_summary(self._gear_tables),
            "physics": physics_view,
            "rigid_physics": self._rigid_physics.frame(),
            "chunks": {
                "loaded": chunks,
                "loaded_count": len(chunks),
                "capacity": MAX_CHUNKS,
                "interest_radius": world.DEFAULT_INTEREST_RADIUS,
            },
            "network": network_view,
            "replay": {
                "recording": self._recording,
                "replaying": self._replaying,
                "recorded_inputs": len(self._recorded_inputs),
                "max_inputs": MAX_REPLAY_INPUTS,
                "replay_index": self._replay_index,
            },
            "world": world_view,
            "content": content_catalog.content_summary(self._content),
            "economy": economy_view,
            "combat": combat_view,
            "factions": factions_contract.view(self._faction_state),
            "quests": quests_contract.view(self._quest_state, self._quest_catalog),
            "dialogue": dialogue_view,
            "quest_dialog": self._quest_dialog_view_locked(),
            "social": social_view,
            "world_events": world_events_view,
            "content_packs": content_catalog.content_pack_summary(
                self._content,
                self._available_content_packs,
            ),
            "inventory": {
                "counts": dict(self._inventory),
                "loot_items": list(self._loot_items[-12:]),
            },
            "bank": self._stash_view_locked(),
            "merchant": self._merchant_view_locked(),
            "loot": self._loot_view_locked(),
            "crafting": {
                "book": self._craft_book_view_locked(),
                "ammunition_recipes": [dict(id=recipe['id'],name=ammo['name'],ammo_id=ammo['id'],
                    inputs=dict(recipe['inputs']),quantity=recipe['output'][ammo['id']],
                    can_craft=self._profession_known_locked(recipe.get('profession','SURVIVAL')) and
                    all(int(self._inventory.get(k,0))>=v for k,v in recipe['inputs'].items()))
                    for slug,ammo in firearms_contract.AMMO.items()
                    for recipe in [self._gear_tables['recipes']['recipe.ammo_'+slug]]],
                "recipes": [key for key in self._content.get("recipes", {})
                            if self._profession_known_locked('SURVIVAL')],
                "gear_recipes": [key for key,recipe in self._gear_tables.get("recipes", {}).items()
                                 if self._profession_known_locked(recipe.get('profession','SURVIVAL'))
                                ][: gear_contract.MAX_RECIPE_OUTPUTS * 2],
                "workstations": [dict(station, y=self._terrain_height_locked(station['x'], station['z']))
                                 for station in gear_contract.world_stations(self._gear_tables)],
                "professions": copy.deepcopy(self._profession_state),
                "last_result": dict(self._last_crafting),
            },
            "trade": trade_contract.view(self._last_trade),
            "progression": dict(progression.summary(self._progression), talent_definitions=[
                {'id':key,'name':str(row.get('name',key))}
                for key,row in self._content.get('talents',{}).items()
                if key in self._progression.get('talents',{}) and isinstance(row,dict)][:32]),
            "editor": editor_contract.summary(self._editor_document),
            "cinematic": cinematic_view,
            "events": list(reversed(self._events[-12:])),
            "event_journal": event_journal_view,
            "dos": dos_view,
            "capabilities": [
                "FIXED_STEP",
                "DATA_ORIENTED_POOLS",
                "SPATIAL_GRID_BROADPHASE",
                "PARTICLE_POOL",
                "CHUNK_INTEREST",
                "WORLD_CELL_COORDINATES",
                "CAMERA_RELATIVE_RENDER_SEAM",
                "WOW_CLASSIC_MOVEMENT_GRAMMAR",
                "REMAPABLE_KEYBINDINGS",
                "DATA_DRIVEN_ADDON_REGISTRY",
                "PITBULL_STYLE_UNITFRAME_SEAM",
                "DETERMINISTIC_TERRAIN_BIOMES",
                "CONTINUOUS_WATER_SURFACE",
                "CELL_LOD_VISIBILITY_DATA",
                "TERRAIN_CELL_TARGETING_BRUSH",
                "SUBCELL_TERRAIN_SCULPTING",
                "TERRAIN_LOD_SKIRT_SEAMS",
                "MOVEMENT_MODE_GROUND_SWIM_FLY",
                "DETERMINISTIC_REPLAY",
                "LOCAL_SNAPSHOT_SEAM",
                "DATA_DRIVEN_ABILITIES_LOOT_CRAFTING",
                "NPC_FIXED_STEP_STEERING",
                "NPC_RADIAL_PERCEPTION",
                "NPC_LINE_OF_SIGHT_BOUNDED",
                "NPC_STIMULUS_MEMORY",
                "NPC_INTERACTION_TARGET",
                "AUTHORED_DIALOGUE_CHOICE_GRAPHS",
                "DIALOGUE_EFFECTS_ATOMIC_WITH_QUESTS",
                "QUEST_PREREQUISITES_AND_CHAINS",
                "AUTHORED_CONTENT_PACK_STREAMING",
                "CONTENT_PACK_ATOMIC_REBIND",
                "SCHEDULED_FACTION_WORLD_EVENTS",
                "WORLD_EVENT_REAL_GROUND_REWARDS",
                "PERSISTED_CONTENT_PACK_SELECTION",
                "NPC_DURABLE_SOCIAL_RELATIONSHIPS",
                "NPC_TO_NPC_COMBAT_EVENTS",
                "AMBIENT_TO_PHYSICAL_POPULATION_PROMOTION",
                "NPC_BOUNDED_HOME_RADIUS",
                "INDIVIDUAL_NPC_STATE",
                "BOUNDED_NPC_MEMORY",
                "NPC_NEEDS_GOALS_INVENTORY",
                "NPC_WORLD_USE_STIMULI",
                "NPC_MATERIALIZED_ITEM_INSTANCES",
                "ATOMIC_NPC_PLAYER_ITEM_TRADE",
                "NPC_VENDOR_ECONOMY",
                "ATOMIC_VENDOR_GOLD_TRANSACTIONS",
                "NPC_PROGRESSIONS_SHARED_XP_CURVE",
                "NPC_GEAR_POWER_EVALUATION",
                "NPC_AUTONOMOUS_LOOT_UPGRADES",
                "NPC_PROFESSION_QUALITY_PROGRESS",
                "NPC_ASCENSION_PARAGON",
                "FIXED_STEP_COMBAT_ACTOR_STATE",
                "REAL_COMBAT_LOOT_DROPS",
                "NPC_RETALIATION_AND_RESPAWN",
                "QUEST_OBJECTIVE_EVENT_BINDING",
                "ATOMIC_QUEST_REWARDS",
                "FACTION_REPUTATION_DISPOSITION",
                "INDIVIDUAL_DAILY_SCHEDULES",
                "TILED_NAVMESH_HEIGHTFIELD",
                "BOUNDED_ASTAR_PATH_SEAM",
                "CHARACTER_SHARED_LOW_POLY_BODY",
                "CHARACTER_PHASED_MESH_VARIANTS",
                "DETERMINISTIC_ROOT_POSE",
                "AUTHORED_GLTF2_ASSET_IMPORT",
                "SKINNED_ASSET_POSE_SEAM",
                "BOUNDED_AUTHORED_ASSET_INSTANCES",
                "AUTHORED_STATIC_ITEM_ASSETS",
                "BOUNDED_AUTHORED_ITEM_INSTANCES",
                "DATA_DRIVEN_ITEM_DEFINITIONS",
                "ITEM_INSTANCE_WORLD_STATE",
                "ITEM_RARITY_LADDER",
                "ITEM_LOOT_TABLE_ROLLS",
                "ITEM_GROUND_CONTAINER_INVENTORY_EQUIPMENT",
                "BOUNDED_ITEM_INTERACTIONS",
                "GEAR_SLOT_TABLE",
                "GEAR_SOCKETED_RUNES_GEMS",
                "GEAR_EXACT_ORDER_RUNEWORDS",
                "GEAR_ENCHANTMENT_LAYER",
                "SURVIVAL_WORKSTATION_CRAFTING",
                "BOUNDED_ASSET_REGISTRY",
                "BOUNDED_AMBIENT_LIFE_PROXIES",
                "DATA_DRIVEN_AMBIENT_SCHEDULES",
                "BOUNDED_PLAYER_STIMULI",
                "IN_GAME_EDITOR_DOCUMENT_UNDO",
                "IN_GAME_TERRAIN_AUTHORING_UNDO",
                "PROGRESSION_TALENTS_ASCENSION_PARAGON",
                "RENDER_PROFILE_AA_UPSCALER_POLICY",
                "MEMORY_PERSISTENCE_MMO_SEAM",
                "CINEMATIC_DIORAMA_COMPOSITION",
                "DUAL_PRESENTATION_RICH_3D_DOS_2D",
                "PRESENTATION_ONLY_FAILOVER",
                "SHARED_FALLBACK_ENTITY_ITEM_DATA",
                "DOS_BOUNDED_COMMAND_GRAMMAR",
                "DOS_CANONICAL_INPUT_DISPATCH",
                "AUTHORITATIVE_EVENT_JOURNAL",
                "MONOTONIC_EVENT_SEQUENCE",
                "PERSISTED_WORLD_TRANSITION_AUDIT",
            ],
        }
        if getattr(self,'_engine_world',None) is not None:snapshot['player']['engine_world']=self._engine_world.environment(self._x[0],self._y[0],self._z[0])
        self._remember_render_snapshot_locked(snapshot)
        self._ui_snapshot_base=self._ui_status_from_snapshot(snapshot)
        return snapshot

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self.snapshot_locked()

    def render_snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self.render_snapshot_locked()

    @staticmethod
    def _compact_ui_item_row(row: Any) -> dict[str, Any]:
        """Keep the inventory inspector useful without shipping item internals."""
        source = row if isinstance(row, dict) else {}
        compact = {
            key: source.get(key)
            for key in (
                "instance_id",
                "definition_id",
                "name",
                "quantity",
                "stack_limit",
                "slot_index",
                "kind",
                "rarity",
                "rarity_color",
                "location",
                "equipped_slot",
                "equip_slot",
                "scroll_enchant_id",
                "scroll_description",
                "equip_slots",
                "firearm",
                "magazine",
                "wielding_reference",
                "weapon_subtype",
                "appearance_index",
                "icon",
                "condition",
            )
            if key in source
        }
        gear = source.get("gear")
        if isinstance(gear, dict):
            compact["gear"] = {
                key: gear.get(key)
                for key in (
                    "socket_count",
                    "socket_capacity",
                    "runeword",
                    "enchantments",
                )
                if key in gear
            }
        return compact

    @classmethod
    def _compact_ui_npc_row(cls, row: Any) -> dict[str, Any]:
        """Preserve the NPC tracker fields, not each NPC's full memory ledger."""
        source = row if isinstance(row, dict) else {}
        compact = {
            key: source.get(key)
            for key in (
                "id",
                "entity_id",
                "archetype",
                "state",
                "x",
                "y",
                "z",
                "yaw",
                "speed",
                "stimulus",
                "line_of_sight",
                "path_status",
                "path_nodes",
                "path_index",
                "combat",
            )
            if key in source
        }
        individual = source.get("individual")
        if isinstance(individual, dict):
            progression = individual.get("progression")
            world_action = individual.get("world_action")
            compact["individual"] = {
                "progression": {
                    key: progression.get(key)
                    for key in (
                        "level",
                        "spec",
                        "power_score",
                        "gear_score",
                    )
                    if isinstance(progression, dict) and key in progression
                },
                "world_action": {
                    key: world_action.get(key)
                    for key in ("last_action", "status", "count")
                    if isinstance(world_action, dict) and key in world_action
                },
            }
        return compact

    @classmethod
    def _ui_status_from_snapshot(cls, snapshot: dict[str, Any]) -> dict[str, Any]:
        """Build a bounded UI delta over the last full authoritative snapshot.

        This is a transport/view optimization only.  The values are taken
        from the same locked snapshot as the simulation; no gameplay state is
        approximated or maintained separately for the UI.
        """
        ui: dict[str, Any] = {
            "schema": "gg.game-engine.ui-delta.v1",
            "state": snapshot.get("state", "IDLE"),
            "mode": snapshot.get("mode", "LOCAL_PLAYGROUND"),
            "stress": bool(snapshot.get("stress", False)),
            "error": str(snapshot.get("error", "")),
        }
        # These sections are small, dynamic inspector data.  Large immutable
        # catalogues, terrain cells and render entities stay on their full or
        # compact streams and are never reparsed for an ordinary movement tick.
        for key in (
            "simulation",
            "player",
            "input",
            "controller",
            "network",
            "replay",
            "chunks",
            "navigation",
            "terrain_editor",
            "gear",
            "physics",
            "economy",
            "merchant",
            "loot",
            "combat",
            "combat_live",
            "actions",
            "factions",
            "quests",
            "dialogue",
            "quest_dialog",
            "social",
            "living_world",
            "world_events",
            "content_packs",
            "crafting",
            "progression",
            "editor",
            "cinematic",
            "events",
            "event_journal",
            "dos",
            "trade",
        ):
            if key in snapshot:
                ui[key] = snapshot[key]

        life = snapshot.get("life")
        if isinstance(life, dict):
            ui["life"] = {
                key: life[key]
                for key in (
                    "schema",
                    "version",
                    "clock",
                    "population",
                    "budget",
                    "visible",
                    "simulation",
                    "activities",
                    "stimuli",
                )
                if key in life
            }

        people = snapshot.get("people")
        if isinstance(people, dict):
            ui["people"] = {
                key: people[key]
                for key in (
                    "schema",
                    "version",
                    "population",
                    "budget",
                    "active",
                    "unique_names",
                    "activities",
                    "average_needs",
                    "memory_events",
                    "progression",
                    "simulation",
                    "policy",
                )
                if key in people
            }

        npc = snapshot.get("npc")
        if isinstance(npc, dict):
            ui["npc"] = {
                key: npc[key]
                for key in (
                    "schema",
                    "version",
                    "active",
                    "capacity",
                    "decision_hz",
                    "movement_hz",
                    "perception",
                    "navigation",
                    "states",
                    "interaction",
                )
                if key in npc
            }
            agents = npc.get("agents")
            if isinstance(agents, list):
                ui["npc"]["agents"] = [
                    cls._compact_ui_npc_row(row) for row in agents[:4]
                ]

        items = snapshot.get("items")
        if isinstance(items, dict):
            ui["items"] = {
                key: items[key]
                for key in (
                    "schema",
                    "version",
                    "instances",
                    "catalog",
                    "counts",
                    "interaction_target",
                )
                if key in items
            }
            for location in ("ground", "equipment", "inventory"):
                rows = items.get(location)
                if isinstance(rows, list):
                    ui["items"][location] = [
                        cls._compact_ui_item_row(row) for row in rows
                    ]

        bank = snapshot.get("bank")
        if isinstance(bank, dict):
            ui["bank"] = {
                key: bank.get(key)
                for key in ("schema", "capacity", "revision", "accessible", "nearby", "focused", "container_id", "loot_count", "error")
            }
            ui["bank"]["items"] = [
                cls._compact_ui_item_row(row)
                for row in bank.get("items", [])[:mmo.MAX_STASH_SLOTS]
                if isinstance(row, dict)
            ]

        terrain = snapshot.get("terrain")
        if isinstance(terrain, dict):
            # Keep the cell/heightfield catalogue on the full stream, but the
            # small player surface readout follows movement at UI cadence.
            surface = terrain.get("player_surface")
            if isinstance(surface, dict):
                ui["terrain_surface"] = dict(surface)

        chunks = snapshot.get("chunks")
        if isinstance(chunks, dict):
            ui["chunks"] = {
                key: chunks[key]
                for key in ("loaded_count", "capacity", "interest_radius")
                if key in chunks
            }
        navigation = snapshot.get("navigation")
        if isinstance(navigation, dict):
            ui["navigation"] = {
                key: navigation[key]
                for key in (
                    "schema",
                    "model",
                    "movement_mode",
                    "tile_size_m",
                    "tiles_per_cell",
                    "streaming",
                    "walkable_tiles",
                    "blocked_tiles",
                    "player_tile",
                    "limits",
                    "integration",
                )
                if key in navigation
            }
        return ui

    def ui_snapshot_locked(self) -> dict[str, Any]:
        """Refresh dynamic inspector state without rebuilding catalogs or terrain."""
        if not getattr(self,"_ui_snapshot_base",None):self.snapshot_locked()
        ui=dict(self._ui_snapshot_base)
        player=dict(ui.get("player",{}))
        player['client_controls']=self._client_controls_view_locked()
        player['world_map']=self._instance_map_descriptor_locked()
        player['ride_frame']=self._ride_view_locked()
        player.pop('engine_world',None)
        if getattr(self,'_engine_world',None) is not None:player['engine_world']=self._engine_world.environment(self._x[0],self._y[0],self._z[0])
        player.update(x=self._x[0],y=self._y[0],z=self._z[0],yaw=self._yaw[0],
            time_s=self._sim_time,movement_mode=self._movement_mode,vehicle=self._vehicle_kind,
            grounded=self._grounded,jump_stage=self._jump_count,sprinting=self._sprinting,
            speed=math.sqrt(self._vx[0]**2+self._vy[0]**2+self._vz[0]**2))
        surface=self._player_surface_locked();player.update(medium=surface['medium'],surface_height=surface['height_m'],biome=surface['biome'])
        ui['terrain_surface']={**ui.get('terrain_surface',{}),**surface}
        ui.update(state="RUNNING" if self._running else "PAUSED",player=player)
        # Contact-bound panels must close on ordinary movement too; the
        # retained catalogue snapshot alone cannot decide current reach.
        ui['loot'] = self._loot_view_locked()
        ui['crafting'] = dict(ui.get('crafting', {}), book=self._craft_book_view_locked())
        combat=combat_contract.view(self._combat_state)
        combat.update(resource=self._resource,resource_capacity=100,cooldowns=dict(self._ability_cooldowns))
        ui["combat"]=combat
        ui['actions']=self._action_view_locked()
        ui['combat_live']={'resource':self._resource,'resource_capacity':100,
            'cooldowns':dict(self._ability_cooldowns),'profile':self._player_combat_profile_locked(),
            'player':dict(self._combat_state.get('actors',{}).get('player',{}))}
        npcs=dict(ui.get("npcs",{}))
        rows=[{"id":self._npc_ids[i],"x":self._x[i],"z":self._z[i],"alive":self._alive[i],
               "archetype":self._npc_archetype[i],"state":"DEAD" if not self._combat_state.get('actors',{}).get(self._npc_ids[i],{}).get('alive',True) else self._npc_state[i]}
              for i in self._npc_indices if self._alive[i]]
        target=npc_contract.nearest_interaction_target(rows,self._x[0],self._z[0])
        regional=self._regional_interaction_target_locked()
        if regional and (not target or regional['distance_m']<target['distance_m']):target=regional
        npcs["interaction"]=npc_contract.build_interaction_view(target,self._npc_last_interaction)
        ui["npcs"]=npcs
        return ui

    def ui_snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self.ui_snapshot_locked()

    def shutdown(self) -> None:
        with self._lock:
            self._running = False
            self._stop.set()
            thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)
        with self._lock:
            self._thread = None
            self._rigid_physics.close()


_RUNTIME = GameEngineRuntime()


def physics_command(request):
    return _RUNTIME.physics_command(request)


def physics_status_payload():
    return _RUNTIME.physics_status()


def status_payload() -> dict[str, Any]:
    return _RUNTIME.snapshot()


def character_create(request: Any) -> dict[str, Any]:
    return _RUNTIME.character_create(request)


def render_status_payload() -> dict[str, Any]:
    return _RUNTIME.render_snapshot()


def presentation_payload() -> dict[str, Any]:
    """Nonblocking consumer of the fixed 60 Hz presentation producer."""
    frame = getattr(_RUNTIME, '_published_frame', None)
    if frame is not None and _RUNTIME._running:
        return frame
    return _RUNTIME.render_snapshot()


def ui_status_payload() -> dict[str, Any]:
    return _RUNTIME.ui_snapshot()


def start() -> dict[str, Any]:
    return _RUNTIME.start()


def cycle_target(reverse: bool = False) -> dict[str, Any]:
    return _RUNTIME.cycle_target(reverse)


def clear_target() -> dict[str, Any]:
    return _RUNTIME.clear_target()


def start_render() -> dict[str, Any]:
    return _RUNTIME.start_render()


def pause() -> dict[str, Any]:
    return _RUNTIME.pause()


def pause_render() -> dict[str, Any]:
    return _RUNTIME.pause_render()


def reset() -> dict[str, Any]:
    return _RUNTIME.reset()


def step() -> dict[str, Any]:
    return _RUNTIME.step()


def set_movement_mode(mode: str) -> dict[str, Any]:
    return _RUNTIME.set_movement_mode(mode)


def explore_region(region_id: str) -> dict[str, Any]:
    return _RUNTIME.explore_region(region_id)


def mobility_action(action: str) -> dict[str, Any]:
    return _RUNTIME.mobility_action(action)


def mobility_water_clock() -> dict[str, Any]:
    return _RUNTIME.mobility_water_clock()


def activate_ability(ability_id: str = "ability.surge") -> dict[str, Any]:
    return _RUNTIME.activate_ability(ability_id)


def reload_firearms() -> dict[str, Any]:
    return _RUNTIME.reload_firearms()


def attack(target_id: str = "", action_id: str = "basic_attack") -> dict[str, Any]:
    return _RUNTIME.attack(target_id, action_id)


def accept_quest(quest_id: str = "quest.shoreline-first") -> dict[str, Any]:
    return _RUNTIME.accept_quest(quest_id)


def claim_quest(quest_id: str = "") -> dict[str, Any]:
    return _RUNTIME.claim_quest(quest_id)


def claim_loot(seed: int | None = None) -> dict[str, Any]:
    return _RUNTIME.claim_loot(seed)


def craft_recipe(recipe_id: str = "recipe.field_ration") -> dict[str, Any]:
    return _RUNTIME.craft_recipe(recipe_id)


def craft_gear(
    recipe_id: str = "recipe.fiber_rope",
    station_id: str = "",
) -> dict[str, Any]:
    return _RUNTIME.craft_gear(recipe_id, station_id)


def socket_item(
    instance_id: str = "",
    insertable_id: str = "",
) -> dict[str, Any]:
    return _RUNTIME.socket_item(instance_id, insertable_id)


def enchant_gear(
    instance_id: str = "",
    enchant_id: str = "",
) -> dict[str, Any]:
    return _RUNTIME.enchant_gear(instance_id, enchant_id)


def enchant_last_loot(enchant_id: str = "enchant.wayfinder") -> dict[str, Any]:
    return _RUNTIME.enchant_last_loot(enchant_id)


def pickup_item(instance_id: str = "") -> dict[str, Any]:
    return _RUNTIME.pickup_item(instance_id)


def open_container(instance_id: str = "") -> dict[str, Any]:
    return _RUNTIME.open_container(instance_id)


def loot_container(instance_id: str = "") -> dict[str, Any]:
    return _RUNTIME.loot_container(instance_id)


def equip_item(instance_id: str = "", slot: str = "") -> dict[str, Any]:
    return _RUNTIME.equip_item(instance_id,slot)


def unequip_item(instance_id: str) -> dict[str, Any]:
    return _RUNTIME.unequip_item(instance_id)


def move_inventory_slot(instance_id: str, slot_index: int) -> dict[str, Any]:
    return _RUNTIME.move_inventory_slot(instance_id, slot_index)

def move_equipment_to_inventory(instance_id: str, slot_index: int) -> dict[str, Any]:
    return _RUNTIME.move_equipment_to_inventory(instance_id, slot_index)

def transfer_inventory_stack(instance_id: str, slot_index: int, count: int) -> dict[str, Any]:
    return _RUNTIME.transfer_inventory_stack(instance_id, slot_index, count)


def drop_item(instance_id: str = "") -> dict[str, Any]:
    return _RUNTIME.drop_item(instance_id)


def deposit_to_stash(instance_id: str, slot_index: int = -1) -> dict[str, Any]:
    return _RUNTIME.deposit_to_stash(instance_id, slot_index)


def withdraw_from_stash(instance_id: str, slot_index: int = -1) -> dict[str, Any]:
    return _RUNTIME.withdraw_from_stash(instance_id, slot_index)


def move_stash_slot(instance_id: str, slot_index: int) -> dict[str, Any]:
    return _RUNTIME.move_stash_slot(instance_id, slot_index)


def interact_item() -> dict[str, Any]:
    return _RUNTIME.interact_item()


def grant_experience(amount: int = 25) -> dict[str, Any]:
    return _RUNTIME.grant_experience(amount)


def add_talent(talent_id: str = "trailblazer") -> dict[str, Any]:
    return _RUNTIME.add_talent(talent_id)


def select_race(race: str = "ISLANDER") -> dict[str, Any]:
    return _RUNTIME.select_race(race)


def select_spec(spec: str = "EXPLORER") -> dict[str, Any]:
    return _RUNTIME.select_spec(spec)


def editor_place(kind: str = "PROP") -> dict[str, Any]:
    return _RUNTIME.editor_place(kind)


def editor_undo() -> dict[str, Any]:
    return _RUNTIME.editor_undo()


def npc_interact() -> dict[str, Any]:
    return _RUNTIME.npc_interact()


def talk_npc(npc_id: str = "", choice_id: str = "") -> dict[str, Any]:
    return _RUNTIME.talk_npc(npc_id, choice_id)


def activate_content_pack(pack_id: str = "pack.tidefall-frontier") -> dict[str, Any]:
    return _RUNTIME.activate_content_pack(pack_id)


def trade_items(
    npc_id: str = "",
    give_instance_id: str = "",
    receive_instance_id: str = "",
) -> dict[str, Any]:
    return _RUNTIME.trade_items(npc_id, give_instance_id, receive_instance_id)


def vendor_buy(
    vendor_id: str = "",
    instance_id: str = "",
) -> dict[str, Any]:
    return _RUNTIME.vendor_buy(vendor_id, instance_id)


def vendor_sell(
    vendor_id: str = "",
    instance_id: str = "",
) -> dict[str, Any]:
    return _RUNTIME.vendor_sell(vendor_id, instance_id)


def terrain_edit(
    operation: str = "RAISE",
    cell_x: int | None = None,
    cell_z: int | None = None,
) -> dict[str, Any]:
    return _RUNTIME.terrain_edit(operation, cell_x, cell_z)


def terrain_brush_edit(
    operation: str = "RAISE",
    cell_x: int | None = None,
    cell_z: int | None = None,
    center_x_m: float | None = None,
    center_z_m: float | None = None,
    radius_m: float = 4.0,
    falloff: str = "SMOOTH",
) -> dict[str, Any]:
    return _RUNTIME.terrain_brush_edit(
        operation,
        cell_x,
        cell_z,
        center_x_m,
        center_z_m,
        radius_m,
        falloff,
    )


def terrain_undo() -> dict[str, Any]:
    return _RUNTIME.terrain_undo()


def save_state() -> dict[str, Any]:
    return _RUNTIME.save_state()


def load_state() -> dict[str, Any]:
    return _RUNTIME.load_state()


def set_render_profile(profile: str) -> dict[str, Any]:
    return _RUNTIME.set_render_profile(profile)


def set_presentation_mode(mode: str) -> dict[str, Any]:
    return _RUNTIME.set_presentation_mode(mode)


def report_graphics_failure(reason: str = "GRAPHICS_STAGE_FAILURE") -> dict[str, Any]:
    return _RUNTIME.report_graphics_failure(reason)


def set_cinematic_preset(preset: str) -> dict[str, Any]:
    return _RUNTIME.set_cinematic_preset(preset)


def set_input(raw: str) -> dict[str, Any]:
    return _RUNTIME.set_input(raw)


def client_control(raw: str) -> dict[str, Any]:
    return _RUNTIME.client_control(raw)


def client_controls_batch(raw: str) -> dict[str, Any]:
    return _RUNTIME.client_controls_batch(raw)


def set_input_render(raw: str) -> dict[str, Any]:
    return _RUNTIME.set_input_render(raw)


def dos_command(raw: str) -> dict[str, Any]:
    return _RUNTIME.dos_command(raw)


def set_keybinding(action: str, key: str) -> dict[str, Any]:
    return _RUNTIME.set_keybinding(action, key)


def reset_keybindings() -> dict[str, Any]:
    return _RUNTIME.reset_keybindings()


def set_addon(addon_id: str, enabled: bool) -> dict[str, Any]:
    return _RUNTIME.set_addon(addon_id, enabled)


def burst() -> dict[str, Any]:
    return _RUNTIME.burst()


def set_stress(enabled: bool) -> dict[str, Any]:
    return _RUNTIME.set_stress(enabled)


def start_recording() -> dict[str, Any]:
    return _RUNTIME.start_recording()


def stop_recording() -> dict[str, Any]:
    return _RUNTIME.stop_recording()


def play_replay() -> dict[str, Any]:
    return _RUNTIME.play_replay()


def shutdown() -> None:
    _RUNTIME.shutdown()
