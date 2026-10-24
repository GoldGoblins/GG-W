"""Bounded authored character- and item-asset import contract for the GAME ENGINE.

The runtime simulation must not know anything about a mesh file.  This module
therefore owns the small, deterministic seam between an authored glTF 2.0
asset and the existing animation contract.  It validates local assets before
QtQuick3D's RuntimeLoader sees them, exposes clip names and budgets to the
snapshot, and returns an explicit shared low-poly fallback for anything that
is not safe or complete enough for the current character slot.

The validator is intentionally a manifest reader, not a second glTF renderer.
QtQuick3D remains responsible for decoding geometry, materials and skinning;
the backend only checks bounded structure and keeps the simulation data-only.
Static item meshes use the same gate but have a separate loader budget and
never enter the skinned character slot.  A character has one active visual
model: the authored model when it has real visual children, otherwise one
shared low-poly character geometry.  Missing animation clips do not justify a
second body; the binding reports ROOT_POSE_ONLY and the root pose remains
authoritative.
"""

from __future__ import annotations

import base64
import copy
import json
import math
import struct
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from backend.platform_support import local_file_path


SCHEMA = "gg.game-engine.assets.v1"

# Enterable stilt hut in local mesh units (Y -1 ground, +1 ridge).
# World size is this times entity sx/sy/sz.  Collision uses the same layout.
HUT_DECK_LOCAL_Y = -0.359
HUT_DECK_HX = 1.005
HUT_DECK_HZ = 0.870
HUT_WALL_HX = 0.625
HUT_WALL_HZ = 0.516
HUT_WALL_T = 0.038
HUT_DOOR_HALF = 0.261
HUT_LADDER_Z = -0.967
HUT_PLAYER_CLEARANCE = 0.32
GLTF_VERSION = "2.0"
SUPPORTED_EXTENSIONS = {".gltf", ".glb"}

# Keep the first runtime importer deliberately small.  These are admission
# limits, not targets for production content; a later offline compiler can
# produce optimized .qml/.mesh packages for larger assets.
MAX_SOURCE_BYTES = 16 * 1024 * 1024
MAX_REFERENCED_BYTES = 32 * 1024 * 1024
MAX_MESHES = 32
MAX_PRIMITIVES = 64
MAX_VERTICES = 200_000
MAX_JOINTS = 128
MAX_ANIMATIONS = 60
MAX_AUTHORED_INSTANCES = 8
# Full articulated rigs remain bounded to eight. Extra crowd residents use
# compact rigs, never a full rig outside the near-character budget.
# Player, six current physical NPCs and up to twenty-four life proxies fit
# within this total while leaving the full-rig cap untouched.
MAX_AUTHORED_CROWD_INSTANCES = 32
MAX_CROWD_JOINTS = 32
MAX_AUTHORED_ITEM_INSTANCES = 24
MAX_STATIC_ITEM_DEFINITIONS = 256

PROCEDURAL_CHARACTER_MODE = "PROCEDURAL_GEOMETRY"
PROCEDURAL_CHARACTER_ASSET_ID = "gg-clay-crowd-character"
PROCEDURAL_CHARACTER_STYLE_ID = "GG_CLAY_LOW_POLY"
PROCEDURAL_CHARACTER_VERTEX_RECORDS = 1020
PROCEDURAL_CHARACTER_TRIANGLES = 1592
PROCEDURAL_CHARACTER_VERTEX_STRIDE = 40
PROCEDURAL_CHARACTER_POSE_VARIANTS = 32
PROCEDURAL_ASSET_MODE = "PROCEDURAL_GEOMETRY"
PROCEDURAL_ASSET_VERTEX_STRIDE = 40
PROCEDURAL_ASSET_MAX_FAMILIES = 96
PROCEDURAL_ASSET_STYLE_ID = "GG_CLAY_ASSET_KIT"
PROCEDURAL_ASSET_STYLE_VERSION = "v1"
WORLD_PROP_ASSET_FAMILIES = (
    "world.prop.rock",
    "world.prop.mangrove",
    "world.prop.shrine",
    "world.prop.barrel",
    "world.ramp",
    "world.tidehouse",
    "world.lantern",
    "world.spawn_marker",
    "world.stress_pebble",
    "world.market_stall",
    "world.fish_rack",
    "world.boat",
    "world.bridge",
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ASSET_ROOT = (PROJECT_ROOT / "qml" / "assets").resolve()
@lru_cache(maxsize=1024)
def inventory_icon(definition_id: str, appearance_index: int = 0) -> str:
    """Resolve only packaged icons; unavailable item art uses the existing unknown image."""
    key=str(definition_id);root=ASSET_ROOT/'authored/items/icons';names=[]
    if key.startswith(('item.','container.')):
        prefix,slug=key.split('.',1)
        if slug and all(c.isascii() and (c.isalnum() or c=='_') for c in slug):
            stem=('itemmesh-' if prefix=='item' else 'container-')+slug
            if 0<appearance_index<36:names.append(stem+'-v'+str(appearance_index)+'.png')
            names.append(stem+'.png')
    for name in (*names,'unknown.png'):
        path=root/name
        if path.is_file() and path.resolve().is_relative_to(root):return path.as_uri()
    return ''
DEFAULT_CHARACTER_ASSET_ID = "gg-codex-original"
DEFAULT_CHARACTER_FILENAME = "authored/characters/gg-crew-brinekip-articulated.glb"
DEFAULT_CHARACTER_SOURCE = ASSET_ROOT / DEFAULT_CHARACTER_FILENAME
DEFAULT_CROWD_CHARACTER_ASSET_ID = "gg-codex-character-flow"
DEFAULT_CROWD_CHARACTER_SOURCE = (
    ASSET_ROOT / "authored" / "characters" / "gg-crew-copperwake-articulated.glb"
)
BLENDER_CHARACTER_SOURCES: dict[str, Path] = {
    "gg-codex-original": DEFAULT_CHARACTER_SOURCE,
    "gg-codex-character-flow": DEFAULT_CROWD_CHARACTER_SOURCE,
    "gg-codex-cartoon-flow": ASSET_ROOT / "authored" / "characters" / "gg-crew-glassfin-articulated.glb",
    "gg-codex-art-flow": ASSET_ROOT / "authored" / "characters" / "gg-crew-mosswake-articulated.glb",
    "gg-codex-mossjaw": ASSET_ROOT / "authored" / "characters" / "gg-crew-mossjaw-articulated.glb",
    "gg-codex-briarstride": ASSET_ROOT / "authored" / "characters" / "gg-crew-briarstride-articulated.glb",
    "gg-codex-riftclaw": ASSET_ROOT / "authored" / "characters" / "gg-crew-riftclaw-articulated.glb",
    "gg-codex-sculpt-flow": ASSET_ROOT / "authored" / "characters" / "gg-crew-tideclaw-articulated.glb",
    "gg-codex-style-flow": ASSET_ROOT / "authored" / "characters" / "gg-crew-reefrunner-articulated.glb",
}
CAST_CHARACTER_SOURCES: dict[str, tuple[str, Path]] = {
    "WANDERER": (
        "gg-codex-character-flow",
        BLENDER_CHARACTER_SOURCES["gg-codex-character-flow"],
    ),
    "GUARDIAN": (
        "gg-codex-riftclaw",
        BLENDER_CHARACTER_SOURCES["gg-codex-riftclaw"],
    ),
    "CRITTER": (
        "gg-codex-mossjaw",
        BLENDER_CHARACTER_SOURCES["gg-codex-mossjaw"],
    ),
}
CROWD_CHARACTER_VARIANT_IDS = (
    "gg-codex-character-flow",
    "gg-codex-cartoon-flow",
    "gg-codex-art-flow",
    "gg-codex-briarstride",
    "gg-codex-riftclaw",
    "gg-codex-sculpt-flow",
    "gg-codex-style-flow",
)
CROWD_LOD_SOURCES: dict[str, Path] = {
    "gg-codex-character-flow-lod": ASSET_ROOT / "authored/characters/gg-crew-copperwake-compact.glb",
    "gg-codex-cartoon-flow-lod": ASSET_ROOT / "authored/characters/gg-crew-glassfin-compact.glb",
    "gg-codex-mossjaw-lod": ASSET_ROOT / "authored/characters/gg-crew-mossjaw-compact.glb",
    "gg-crew-mosswake-crowd": ASSET_ROOT / "authored/characters/gg-crew-mosswake-compact.glb",
    "gg-crew-tideclaw-crowd": ASSET_ROOT / "authored/characters/gg-crew-tideclaw-compact.glb",
    "gg-crew-reefrunner-crowd": ASSET_ROOT / "authored/characters/gg-crew-reefrunner-compact.glb",
    "gg-crew-briarstride-crowd": ASSET_ROOT / "authored/characters/gg-crew-briarstride-compact.glb",
    "gg-crew-riftclaw-crowd": ASSET_ROOT / "authored/characters/gg-crew-riftclaw-compact.glb",
}
# World props authored in the EXT Blender desk.  The engine imports the GLB;
# it does not keep a second Python silhouette for the same asset.
AUTHORED_WORLD_SOURCES: dict[str, dict[str, Any]] = {
    "HOUSE": {
        "asset_id": "gg-sandover-stilt-hut",
        "source": ASSET_ROOT / "authored" / "world" / "gg-coastal-stilt-hut-v3.glb",
        "anchor": "FEET",
        "height_m": 3.68,
        "style_id": "GG_SANDOVER_LOW_POLY",
    },
    "WINDMILL": {
        "asset_id": "gg-sandover-windmill",
        "source": ASSET_ROOT / "authored" / "world" / "gg-sandover-windmill.glb",
        "anchor": "FEET",
        "height_m": 5.18,
        "style_id": "GG_SANDOVER_LOW_POLY",
    },
    "WATER_WHEEL": {
        "asset_id": "gg-sandover-waterwheel",
        "source": ASSET_ROOT / "authored" / "world" / "gg-sandover-waterwheel.glb",
        "anchor": "FEET",
        "height_m": 3.30,
        "style_id": "GG_SANDOVER_LOW_POLY",
    },
    "TIDE_BEACON": {
        "asset_id": "gg-sandover-tide-beacon",
        "source": ASSET_ROOT / "authored" / "world" / "gg-sandover-tide-beacon.glb",
        "anchor": "FEET",
        "height_m": 2.92,
        "style_id": "GG_SANDOVER_LOW_POLY",
    },
    "PALM": {
        "asset_id": "gg-sandover-palm",
        "source": ASSET_ROOT / "authored" / "world" / "gg-sandover-palm.glb",
        "anchor": "FEET",
        "height_m": 4.05,
        "style_id": "GG_SANDOVER_LOW_POLY",
    },
    "DOCK": {
        "asset_id": "gg-sandover-cove-pier",
        "source": ASSET_ROOT / "authored" / "world" / "gg-sandover-cove-pier.glb",
        "anchor": "FEET",
        "height_m": 2.51,
        "style_id": "GG_SANDOVER_LOW_POLY",
    },
    "MANGROVE": {
        "asset_id": "gg-sandover-mangrove",
        "source": ASSET_ROOT / "authored" / "world" / "gg-sandover-mangrove.glb",
        "anchor": "FEET",
        "height_m": 4.0,
        "style_id": "GG_SANDOVER_LOW_POLY",
    },
    "LANTERN": {
        "asset_id": "gg-clay-lantern-post",
        "source": ASSET_ROOT / "authored" / "world" / "gg-clay-lantern-post.glb",
        "anchor": "FEET",
        "height_m": 2.0,
    },
}
# Village houses are a small authored kit. Stable entity variants choose one
# Blender source at scene construction so houses do not repeat one silhouette.
AUTHORED_WORLD_VARIANTS: dict[str, tuple[dict[str, Any], ...]] = {
    "HOUSE": (
        AUTHORED_WORLD_SOURCES["HOUSE"],
        {
            "asset_id": "gg-sandover-roundhouse",
            "source": ASSET_ROOT / "authored" / "world" / "gg-coastal-roundhouse-v3.glb",
            "anchor": "FEET",
            "height_m": 3.68,
            "style_id": "GG_SANDOVER_LOW_POLY",
        },
        {
            "asset_id": "gg-sandover-longhouse",
            "source": ASSET_ROOT / "authored" / "world" / "gg-coastal-longhouse-v3.glb",
            "anchor": "FEET",
            "height_m": 3.68,
            "style_id": "GG_SANDOVER_LOW_POLY",
        },
        {
            "asset_id": "gg-sandover-market-hut",
            "source": ASSET_ROOT / "authored" / "world" / "gg-coastal-market-hut-v3.glb",
            "anchor": "FEET",
            "height_m": 3.68,
            "style_id": "GG_SANDOVER_LOW_POLY",
        },
    ),
}

# Static item meshes use the same local-only admission path as characters.
# These original Blender GLBs cover the complete starter catalogue, including
# the equipment shown on the player and the four ground pickups in Sandover.
DEFAULT_STATIC_ITEM_ASSET_SPECS: dict[str, dict[str, Any]] = {
    "itemmesh.enchant_scroll": {
        "source": ASSET_ROOT / "authored" / "items" / "itemmesh-enchant_scroll.glb",
        "unit_scale": (1.0, 1.0, 1.0),
    },
    "itemmesh.island_compass": {
        "source": ASSET_ROOT / "authored" / "items" / "itemmesh-island_compass.glb",
        "unit_scale": (2.8, 2.8, 2.8),
    },
    "itemmesh.sea_salt": {
        "source": ASSET_ROOT / "authored" / "items" / "itemmesh-sea_salt.glb",
    },
    "itemmesh.sun_herb": {
        "source": ASSET_ROOT / "authored" / "items" / "itemmesh-sun_herb.glb",
    },
    "itemmesh.field_ration": {
        "source": ASSET_ROOT / "authored" / "items" / "itemmesh-field_ration.glb",
    },
    "itemmesh.old_boot": {
        "source": ASSET_ROOT / "authored" / "items" / "itemmesh-old_boot.glb",
    },
    "itemmesh.iron_saber": {
        "source": ASSET_ROOT / "authored" / "items" / "itemmesh-iron_saber.glb",
        "weapon_fx": {
            "authored": {"base": [0.0, 0.18, 0.0], "tip": [0.035, 1.43, 0.0]},
            "native": {"base": [0.0, -0.04, 0.0], "tip": [0.0, 0.65, 0.0]},
        },
    },
    "itemmesh.tideguard_jacket": {
        "source": ASSET_ROOT / "authored" / "items" / "itemmesh-tideguard_jacket.glb",
    },
    "itemmesh.moon_shard": {
        "source": ASSET_ROOT / "authored" / "items" / "itemmesh-moon_shard.glb",
    },
    "itemmesh.sunken_crown": {
        "source": ASSET_ROOT / "authored" / "items" / "itemmesh-sunken_crown.glb",
        "unit_scale": (2.0, 2.0, 2.0),
    },
    "itemmesh.drift_cloak": {
        "source": ASSET_ROOT / "authored" / "items" / "itemmesh-drift_cloak.glb",
    },
    "itemmesh.saltpath_boots": {
        "source": ASSET_ROOT / "authored" / "items" / "itemmesh-saltpath_boots.glb",
    },
    "itemmesh.goblin_totem": {
        "source": ASSET_ROOT / "authored" / "items" / "itemmesh-goblin_totem.glb",
    },
    "container.supply_crate": {
        "source": ASSET_ROOT / "authored" / "items" / "container-supply_crate.glb",
    },
}
from backend.game_engine_asset_variations import WEAPON_FAMILIES
for _family in WEAPON_FAMILIES:
    DEFAULT_STATIC_ITEM_ASSET_SPECS['itemmesh.weapon_'+_family] = {
        'source':ASSET_ROOT/'authored/items'/('weapon-'+_family+'.glb'),
        'unit_scale':(.45,.45,.45) if _family=='pistol' else (1.,1.,1.),
        'weapon_fx':{'authored':{'base':[0.,.34,0.],'tip':[.04,1.45,0.]},
                     'native':{'base':[0.,.18,0.],'tip':[0.,1.,0.]}}
    }
for _produce in ('coconut','banana','apple','pineapple','grapes','juniper'):
    DEFAULT_STATIC_ITEM_ASSET_SPECS['itemmesh.nature.'+_produce] = {
        'source':ASSET_ROOT/'authored/nature'/(_produce+'.glb'), 'unit_scale':(1.,1.,1.)}
from backend.game_engine_firearms import AMMO
for _slug in AMMO:
    DEFAULT_STATIC_ITEM_ASSET_SPECS['itemmesh.ammo_'+_slug]={'source':ASSET_ROOT/'authored/items'/('ammo-'+_slug+'.glb'),'unit_scale':(1.,1.,1.)}

# The names are the stable game-side vocabulary.  An authored file may omit a
# clip; in that case the root pose still works and the importer reports the
# missing clip instead of silently inventing one.
CLIP_BY_MOTION_STATE = {
    "IDLE": "Idle",
    "WALK": "Walk",
    "SPRINT": "Sprint",
    "AIR": "Air",
    "DOUBLE_JUMP": "DoubleJump",
    "GRAPPLE": "Grapple",
    "SWIM": "Swim",
    "FLY": "Fly",
    "HOVERBOARD": "Board",
    "HOVERBOARD_AIR": "BoardAir",
    "BOAT": "Skiff",
    "SIT": "Sit", "SLEEP": "Sleep", "KNEEL": "Kneel",
}

# The character visual seam is deliberately one-model wide.  This is a data
# contract consumed by QML and diagnostics, not a promise that every future
# authored file must remain a box forever.
CHARACTER_VISUAL_POLICY = "SINGLE_CHARACTER_MODEL"
CHARACTER_VISUAL_PREFERRED = "AUTHORED_SKINNED"
CHARACTER_VISUAL_FALLBACK = "SHARED_LOW_POLY_CHARACTER_GEOMETRY"

CHARACTER_STYLE_CONTRACT = {
    "id": PROCEDURAL_CHARACTER_STYLE_ID,
    "version": "v1",
    "surface": "MATTE_FACETED_CLAY",
    "palette": "RGBA_VERTEX_COLORS_NO_TEXTURE",
    "silhouette": "EXAGGERATED_READABLE_HUMANOID",
    "geometry": "ONE_SHARED_INDEXED_MESH",
    "animation": "FIXED_STEP_POSE_BUCKETS",
    "crowd_triangle_budget": PROCEDURAL_CHARACTER_TRIANGLES,
    "pose_variants": PROCEDURAL_CHARACTER_POSE_VARIANTS,
    "reference_policy": "INSPIRATION_ONLY_NO_SOURCE_COPY",
}

ASSET_KIT_STYLE_CONTRACT = {
    "id": PROCEDURAL_ASSET_STYLE_ID,
    "version": PROCEDURAL_ASSET_STYLE_VERSION,
    "surface": "MATTE_FACETED_CLAY",
    "palette": "RGBA_VERTEX_COLORS_NO_TEXTURE",
    "silhouette": "READABLE_GAMEPLAY_SCALE",
    "geometry": "ONE_CACHED_INDEXED_MESH_PER_ASSET_FAMILY",
    "materials": "SHARED_PRINCIPLED_DIELECTRIC",
    "item_state": "GROUND_CONTAINER_INVENTORY_EQUIPPED",
    "reference_policy": "INSPIRATION_ONLY_NO_SOURCE_COPY",
}

# Named empties parented to the clay-hero armature.  The rest offsets are
# gameplay-metre poses relative to the entity root and are used only while
# the authored model is not yet the live visual.  Once RuntimeLoader has
# the SOCKET_* node, equipment parents to that node and the rest pose is
# unused.
CHARACTER_ATTACHMENT_SOCKETS = (
    "HEAD",
    "CHEST",
    "MAIN_HAND",
    "OFF_HAND",
    "BACK",
    "FEET",
)
CHARACTER_SOCKET_REST_M = {
    "HEAD": [0.0, 0.83, 0.0],
    "CHEST": [0.0, 0.07, -0.16],
    "MAIN_HAND": [0.48, -0.29, -0.04],
    "OFF_HAND": [-0.48, -0.29, -0.04],
    "BACK": [0.0, 0.13, 0.22],
    "FEET": [0.0, -0.61, 0.0],
}
SLOT_TO_ATTACHMENT_SOCKET = {
    "HEAD": "HEAD",
    "NECK": "HEAD",
    "SHOULDERS": "CHEST",
    "BACK": "BACK",
    "CHEST": "CHEST",
    "TABARD": "CHEST",
    "FEET": "FEET",
    "MAIN_HAND": "MAIN_HAND",
    "OFF_HAND": "OFF_HAND",
    "RANGED": "MAIN_HAND",
}


for _nature_tool in ("shears", "bucket", "brush", "net", "rod", "knife"):
    DEFAULT_STATIC_ITEM_ASSET_SPECS["itemmesh.nature.tool_" + _nature_tool] = {
        "source": ASSET_ROOT / "authored/nature" / ("tool-" + _nature_tool + ".glb"),
        "asset_class": "TOOL",
    }


def _error(
    asset_id: str,
    code: str,
    message: str,
    *,
    source: str = "",
    file_format: str = "GLTF2",
) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "id": str(asset_id or "unknown-asset"),
        "status": "ERROR",
        "mode": "PREVIEW_FALLBACK",
        "source": "",
        "relative_source": "",
        "root_offset_m": 0.0,
        "format": file_format,
        "skinned": False,
        "animation_mode": "NONE",
        "skeleton": {"skins": 0, "joints": 0, "skinned_primitives": 0},
        "meshes": 0,
        "primitives": 0,
        "vertices": 0,
        "animations": 0,
        "clips": [],
        "bytes": 0,
        "attachment_sockets": {},
        "budget": {
            "max_source_bytes": MAX_SOURCE_BYTES,
            "max_referenced_bytes": MAX_REFERENCED_BYTES,
            "max_authored_instances": MAX_AUTHORED_INSTANCES,
        },
        "error": {"code": str(code), "message": str(message)},
        "requested_source": str(source or ""),
    }


def _safe_vec3(value: Any, default: tuple[float, float, float] = (0.0, 0.0, 0.0)) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) < 3:
        value = default
    result: list[float] = []
    for index, fallback in enumerate(default):
        try:
            number = float(value[index])
        except (TypeError, ValueError, IndexError):
            number = fallback
        result.append(round(number if math.isfinite(number) else fallback, 4))
    return result


def empty_attachment() -> dict[str, Any]:
    return {"socket": "", "node": "", "rest": [0.0, 0.0, 0.0]}


def default_socket_row(socket_id: str) -> dict[str, Any]:
    wanted = str(socket_id or "").strip().upper()
    if wanted not in CHARACTER_ATTACHMENT_SOCKETS:
        return empty_attachment()
    return {
        "id": wanted,
        "socket": wanted,
        "node": f"SOCKET_{wanted}",
        "rest": list(CHARACTER_SOCKET_REST_M[wanted]),
    }


def _extract_attachment_sockets(nodes: Any) -> dict[str, dict[str, Any]]:
    """Read named SOCKET_* empties from a glTF node array."""
    found: dict[str, dict[str, Any]] = {}
    if not isinstance(nodes, list):
        return found
    parents={child:index for index,parent in enumerate(nodes) if isinstance(parent,dict)
        for child in parent.get('children',[]) if isinstance(child,int) and 0<=child<len(nodes)}
    def model_point(index):
        # Socket translations are bone-local. Keep a model-space rest anchor
        # for Qt importers that do not publish the empty as a QObject node.
        point=[0.,0.,0.];visited=set()
        while index not in visited and len(visited)<MAX_JOINTS:
            visited.add(index);node=nodes[index]
            matrix=node.get('matrix')
            if isinstance(matrix,list) and len(matrix)==16:
                point=[sum(float(matrix[k*4+j])*point[k] for k in range(3))+float(matrix[12+j]) for j in range(3)]
            else:
                scale=_safe_vec3(node.get('scale'),(1.,1.,1.));point=[point[i]*scale[i] for i in range(3)]
                q=node.get('rotation',[0.,0.,0.,1.]);x,y,z,w=[float(v) for v in q]
                u,v,t=point;tx=2*(y*t-z*v);ty=2*(z*u-x*t);tz=2*(x*v-y*u)
                rotated=[u+w*tx+y*tz-z*ty,v+w*ty+z*tx-x*tz,t+w*tz+x*ty-y*tx]
                translation=_safe_vec3(node.get('translation'))
                point=[rotated[i]+translation[i] for i in range(3)]
            if index not in parents:break
            index=parents[index]
        return [round(v,6) for v in point]
    for index,node in enumerate(nodes):
        if not isinstance(node, dict):
            continue
        extras = node.get("extras") if isinstance(node.get("extras"), dict) else {}
        name = str(node.get("name") or "").strip()
        socket_id = str(extras.get("gg_socket") or "").strip().upper()
        if not socket_id and name.upper().startswith("SOCKET_"):
            socket_id = name.split("_", 1)[-1].strip().upper()
        if socket_id not in CHARACTER_ATTACHMENT_SOCKETS or socket_id in found:
            continue
        row = default_socket_row(socket_id)
        if name:
            row["node"] = name
        row["local_translation"] = _safe_vec3(node.get("translation"))
        row['model_rest']=model_point(index)
        found[socket_id] = row
    return found


def attachment_for_slot(slot: Any, sockets: Any = None) -> dict[str, Any]:
    """Map one gear slot onto a character attachment socket."""
    wanted = SLOT_TO_ATTACHMENT_SOCKET.get(str(slot or "").strip().upper(), "")
    if not wanted:
        return empty_attachment()
    row = sockets.get(wanted) if isinstance(sockets, dict) else None
    if not isinstance(row, dict):
        row = default_socket_row(wanted)
    rest = _safe_vec3(row.get("rest"), tuple(CHARACTER_SOCKET_REST_M[wanted]))
    node = str(row.get("node") or f"SOCKET_{wanted}").strip() or f"SOCKET_{wanted}"
    return {
        "socket": wanted,
        "node": node,
        "rest": rest,
    }


def _asset_id_for_path(path: Path) -> str:
    stem = path.stem.strip().lower().replace(" ", "-")
    return stem or "authored-asset"


def _path_inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _resolve_local_source(source: Any) -> tuple[Path | None, str | None]:
    """Resolve one source without allowing URLs or path traversal."""
    raw = str(source or "").strip()
    if not raw:
        return None, "ASSET_SOURCE_EMPTY"

    parsed = urlparse(raw)
    is_path = Path(raw).is_absolute() and not raw.lower().startswith('file:')
    if parsed.scheme and not is_path:
        if parsed.scheme != "file" or parsed.netloc not in {"", "localhost"} or parsed.query or parsed.fragment:
            return None, "ASSET_SOURCE_NOT_LOCAL"
        candidate = local_file_path(raw)
    else:
        candidate = Path(raw)
        if not candidate.is_absolute():
            # Both "hero.gltf" and the UI-friendly "assets/hero.gltf" are
            # accepted, but both still resolve under the bundled asset root.
            if candidate.parts and candidate.parts[0].lower() == "assets":
                candidate = ASSET_ROOT.parent.joinpath(*candidate.parts[1:])
            else:
                candidate = ASSET_ROOT / candidate

    try:
        resolved = candidate.resolve(strict=False)
    except OSError:
        return None, "ASSET_SOURCE_UNRESOLVABLE"
    if not _path_inside(resolved, ASSET_ROOT):
        return None, "ASSET_SOURCE_OUTSIDE_ALLOWLIST"
    if resolved.suffix.lower() not in SUPPORTED_EXTENSIONS:
        return None, "ASSET_FORMAT_UNSUPPORTED"
    return resolved, None


def _read_json_document(path: Path) -> tuple[dict[str, Any] | None, bytes, str | None]:
    from backend.game_workflow_common import read_file
    try:
        _, source_bytes = read_file(path, MAX_SOURCE_BYTES)
    except (OSError, ValueError) as exc:
        if str(exc) == "FILE_TOO_LARGE":
            return None, b"", "ASSET_SOURCE_TOO_LARGE"
        return None, b"", "ASSET_SOURCE_UNREADABLE:" + type(exc).__name__
    if len(source_bytes) > MAX_SOURCE_BYTES:
        return None, source_bytes, "ASSET_SOURCE_TOO_LARGE"

    if path.suffix.lower() == ".gltf":
        try:
            document = json.loads(source_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None, source_bytes, "GLTF_JSON_INVALID"
        return (document if isinstance(document, dict) else None), source_bytes, (
            None if isinstance(document, dict) else "GLTF_ROOT_INVALID"
        )

    if len(source_bytes) < 20:
        return None, source_bytes, "GLB_HEADER_INVALID"
    try:
        magic, version, declared_length = struct.unpack_from("<4sII", source_bytes, 0)
    except struct.error:
        return None, source_bytes, "GLB_HEADER_INVALID"
    if magic != b"glTF" or version != 2:
        return None, source_bytes, "GLB_VERSION_UNSUPPORTED"
    if declared_length > len(source_bytes) or declared_length > MAX_SOURCE_BYTES:
        return None, source_bytes, "GLB_LENGTH_INVALID"

    offset = 12
    json_chunk: bytes | None = None
    while offset + 8 <= declared_length:
        chunk_length, chunk_type = struct.unpack_from("<II", source_bytes, offset)
        offset += 8
        end = offset + chunk_length
        if end > declared_length or end > len(source_bytes):
            return None, source_bytes, "GLB_CHUNK_INVALID"
        if chunk_type == 0x4E4F534A:  # ASCII JSON in little-endian uint32 form.
            json_chunk = source_bytes[offset:end].rstrip(b" \t\r\n\x00")
            break
        offset = end
    if json_chunk is None:
        return None, source_bytes, "GLB_JSON_CHUNK_MISSING"
    try:
        document = json.loads(json_chunk.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, source_bytes, "GLB_JSON_INVALID"
    return (document if isinstance(document, dict) else None), source_bytes, (
        None if isinstance(document, dict) else "GLB_ROOT_INVALID"
    )


def _accessor(document: dict[str, Any], index: Any) -> dict[str, Any] | None:
    accessors = document.get("accessors")
    if not isinstance(accessors, list):
        return None
    try:
        safe_index = int(index)
    except (TypeError, ValueError):
        return None
    if safe_index < 0 or safe_index >= len(accessors):
        return None
    value = accessors[safe_index]
    return value if isinstance(value, dict) else None


def _safe_count(accessor: dict[str, Any] | None) -> int:
    if not accessor:
        return 0
    try:
        count = int(accessor.get("count", 0))
    except (TypeError, ValueError):
        return 0
    return max(0, count)


def _validate_buffer_uris(path: Path, document: dict[str, Any]) -> tuple[int, str | None]:
    """Validate referenced buffers without decoding arbitrary remote data."""
    from backend import game_asset_resources as resources
    buffers = document.get("buffers", [])
    if not isinstance(buffers, list):
        return 0, "GLTF_BUFFERS_INVALID"
    total = 0
    for buffer in buffers:
        if not isinstance(buffer, dict):
            return total, "GLTF_BUFFER_INVALID"
        try:
            declared = int(buffer.get("byteLength", 0))
        except (TypeError, ValueError):
            return total, "GLTF_BUFFER_LENGTH_INVALID"
        if declared < 0 or declared > MAX_REFERENCED_BYTES:
            return total, "GLTF_BUFFER_TOO_LARGE"
        uri = buffer.get("uri")
        if uri is not None:
            if not isinstance(uri, str) or not uri:
                return total, "GLTF_BUFFER_URI_INVALID"
            if uri.startswith("data:"):
                try:
                    actual = len(resources.data_uri(uri, MAX_REFERENCED_BYTES - total))
                except (ValueError, UnicodeError):
                    return total, "GLTF_DATA_URI_INVALID"
                if actual > MAX_REFERENCED_BYTES or actual < declared:
                    return total, "GLTF_DATA_URI_LENGTH_INVALID"
            else:
                try:
                    referenced = resources.reference(path, uri, ASSET_ROOT, MAX_REFERENCED_BYTES - total)
                    actual = referenced.stat().st_size
                except ValueError as exc:
                    return total, "GLTF_EXTERNAL_URI_OUTSIDE_ALLOWLIST" if "ROOT" in str(exc) else "GLTF_EXTERNAL_URI_INVALID"
                except OSError:
                    return total, "GLTF_EXTERNAL_URI_MISSING"
                if actual > MAX_REFERENCED_BYTES or actual < declared:
                    return total, "GLTF_EXTERNAL_URI_LENGTH_INVALID"
        total += actual if uri is not None else declared
        if total > MAX_REFERENCED_BYTES:
            return total, "GLTF_REFERENCED_DATA_TOO_LARGE"
    return total, None


def _validate_image_uris(path: Path, document: dict[str, Any]) -> tuple[int, str | None]:
    """Validate texture references before RuntimeLoader opens the asset.

    glTF may keep an image in a bufferView or beside the document.  The first
    runtime seam supports both forms, but external files must remain inside
    the same bundled allowlist as the model.  This prevents a seemingly local
    character from pulling arbitrary files into the renderer.
    """
    from backend import game_asset_resources as resources
    images = document.get("images", [])
    if not isinstance(images, list):
        return 0, "GLTF_IMAGES_INVALID"
    buffer_views = document.get("bufferViews", [])
    if not isinstance(buffer_views, list):
        return 0, "GLTF_BUFFER_VIEWS_INVALID"
    total = 0
    for image in images:
        if not isinstance(image, dict):
            return total, "GLTF_IMAGE_INVALID"
        uri = image.get("uri")
        if uri is None:
            try:
                buffer_view = int(image.get("bufferView", -1))
            except (TypeError, ValueError):
                return total, "GLTF_IMAGE_BUFFER_VIEW_INVALID"
            if buffer_view < 0 or buffer_view >= len(buffer_views):
                return total, "GLTF_IMAGE_BUFFER_VIEW_INVALID"
            view = buffer_views[buffer_view]
            if not isinstance(view, dict):
                return total, "GLTF_IMAGE_BUFFER_VIEW_INVALID"
            try:
                length = int(view.get("byteLength", 0))
            except (TypeError, ValueError):
                return total, "GLTF_IMAGE_LENGTH_INVALID"
            if length < 0 or length > MAX_REFERENCED_BYTES:
                return total, "GLTF_IMAGE_TOO_LARGE"
            continue
        if not isinstance(uri, str) or not uri:
            return total, "GLTF_IMAGE_URI_INVALID"
        if uri.startswith("data:"):
            try:
                actual = len(resources.data_uri(uri, MAX_REFERENCED_BYTES - total))
            except (ValueError, UnicodeError):
                return total, "GLTF_IMAGE_DATA_URI_INVALID"
        else:
            try:
                referenced = resources.reference(path, uri, ASSET_ROOT, MAX_REFERENCED_BYTES - total)
                actual = referenced.stat().st_size
            except ValueError as exc:
                return total, "GLTF_IMAGE_OUTSIDE_ALLOWLIST" if "ROOT" in str(exc) else "GLTF_IMAGE_EXTERNAL_URI_INVALID"
            except OSError:
                return total, "GLTF_IMAGE_MISSING"
        if actual > MAX_REFERENCED_BYTES:
            return total, "GLTF_IMAGE_TOO_LARGE"
        total += actual
        if total > MAX_REFERENCED_BYTES:
            return total, "GLTF_REFERENCED_IMAGES_TOO_LARGE"
    return total, None


def _validate_document(
    path: Path,
    source_bytes: bytes,
    document: dict[str, Any],
    asset_id: str,
) -> dict[str, Any]:
    asset_meta = document.get("asset")
    if not isinstance(asset_meta, dict) or str(asset_meta.get("version", "")) != GLTF_VERSION:
        return _error(asset_id, "GLTF_VERSION_UNSUPPORTED", "Only glTF 2.0 is admitted.", source=str(path))

    referenced_bytes, buffer_error = _validate_buffer_uris(path, document)
    if buffer_error:
        return _error(asset_id, buffer_error, "Referenced buffer data failed the local budget check.", source=str(path))
    image_bytes, image_error = _validate_image_uris(path, document)
    if image_error:
        return _error(asset_id, image_error, "Referenced image data failed the local budget check.", source=str(path))
    referenced_bytes += image_bytes
    if referenced_bytes > MAX_REFERENCED_BYTES:
        return _error(asset_id, "GLTF_REFERENCED_DATA_TOO_LARGE", "Referenced model and image data exceed the runtime admission budget.", source=str(path))

    meshes = document.get("meshes", [])
    nodes = document.get("nodes", [])
    skins = document.get("skins", [])
    animations = document.get("animations", [])
    if not isinstance(meshes, list) or not isinstance(nodes, list):
        return _error(asset_id, "GLTF_SCENE_ARRAYS_INVALID", "Meshes and nodes must be arrays.", source=str(path))
    if not isinstance(skins, list) or not isinstance(animations, list):
        return _error(asset_id, "GLTF_ANIMATION_ARRAYS_INVALID", "Skins and animations must be arrays.", source=str(path))
    if not meshes:
        return _error(asset_id, "GLTF_MESH_MISSING", "The authored asset contains no mesh.", source=str(path))
    if len(meshes) > MAX_MESHES or len(animations) > MAX_ANIMATIONS:
        return _error(asset_id, "GLTF_OBJECT_BUDGET_EXCEEDED", "Mesh or animation count exceeds the runtime admission budget.", source=str(path))

    primitive_count = 0
    vertex_count = 0
    skinned_primitives = 0
    for mesh in meshes:
        if not isinstance(mesh, dict) or not isinstance(mesh.get("primitives", []), list):
            return _error(asset_id, "GLTF_MESH_INVALID", "Every mesh must contain a primitive array.", source=str(path))
        for primitive in mesh["primitives"]:
            primitive_count += 1
            if primitive_count > MAX_PRIMITIVES or not isinstance(primitive, dict):
                return _error(asset_id, "GLTF_PRIMITIVE_BUDGET_EXCEEDED", "Primitive count or shape is outside the admission budget.", source=str(path))
            attributes = primitive.get("attributes", {})
            if not isinstance(attributes, dict) or _accessor(document, attributes.get("POSITION")) is None:
                return _error(asset_id, "GLTF_POSITION_MISSING", "Every primitive needs a valid POSITION accessor.", source=str(path))
            vertex_count += _safe_count(_accessor(document, attributes.get("POSITION")))
            if vertex_count > MAX_VERTICES:
                return _error(asset_id, "GLTF_VERTEX_BUDGET_EXCEEDED", "Vertex count exceeds the runtime admission budget.", source=str(path))
            joints = attributes.get("JOINTS_0")
            weights = attributes.get("WEIGHTS_0")
            if joints is not None or weights is not None:
                if _accessor(document, joints) is None or _accessor(document, weights) is None:
                    return _error(asset_id, "GLTF_SKIN_ATTRIBUTES_INVALID", "JOINTS_0 and WEIGHTS_0 must both reference valid accessors.", source=str(path))
                skinned_primitives += 1

    joint_count = 0
    for skin in skins:
        if not isinstance(skin, dict) or not isinstance(skin.get("joints", []), list):
            return _error(asset_id, "GLTF_SKIN_INVALID", "Every skin must contain a joint array.", source=str(path))
        joints = skin["joints"]
        joint_count += len(joints)
        if joint_count > MAX_JOINTS:
            return _error(asset_id, "GLTF_JOINT_BUDGET_EXCEEDED", "Joint count exceeds the runtime admission budget.", source=str(path))
        for joint in joints:
            try:
                joint_index = int(joint)
            except (TypeError, ValueError):
                return _error(asset_id, "GLTF_JOINT_INDEX_INVALID", "A skin references a non-integer joint.", source=str(path))
            if joint_index < 0 or joint_index >= len(nodes):
                return _error(asset_id, "GLTF_JOINT_INDEX_INVALID", "A skin references a node outside the node array.", source=str(path))

    clips: list[dict[str, Any]] = []
    seen_clip_names: set[str] = set()
    for index, animation in enumerate(animations):
        if not isinstance(animation, dict):
            return _error(asset_id, "GLTF_ANIMATION_INVALID", "Every animation must be an object.", source=str(path))
        name = str(animation.get("name", "") or f"ANIMATION_{index + 1}").strip()
        if not name:
            name = f"ANIMATION_{index + 1}"
        if name in seen_clip_names:
            return _error(asset_id, "GLTF_ANIMATION_NAME_DUPLICATE", "Animation names must be unique.", source=str(path))
        seen_clip_names.add(name)
        samplers = animation.get("samplers", [])
        channels = animation.get("channels", [])
        if not isinstance(samplers, list) or not isinstance(channels, list):
            return _error(asset_id, "GLTF_ANIMATION_INVALID", "Animation samplers and channels must be arrays.", source=str(path))
        duration = 0.0
        for sampler in samplers:
            if not isinstance(sampler, dict):
                return _error(asset_id, "GLTF_ANIMATION_SAMPLER_INVALID", "Animation sampler is not an object.", source=str(path))
            input_accessor = _accessor(document, sampler.get("input"))
            output_accessor = _accessor(document, sampler.get("output"))
            if input_accessor is None or output_accessor is None:
                return _error(asset_id, "GLTF_ANIMATION_ACCESSOR_INVALID", "Animation sampler references a missing accessor.", source=str(path))
            minimum = input_accessor.get("max", [0.0])
            try:
                duration = max(duration, float(minimum[-1] if isinstance(minimum, list) and minimum else 0.0))
            except (TypeError, ValueError):
                duration = 0.0
        clips.append({"name": name, "duration_s": round(max(0.0, duration), 3)})

    skinned = bool(skins and skinned_primitives)
    if skinned:
        mode = "AUTHORED_SKINNED"
        animation_mode = "GLTF_SKINNED"
    elif animations:
        # Kenney's blocky characters are intentionally admitted as a separate
        # mode. They animate node transforms rather than a shared skin, so
        # they must use the timeline adapter and never masquerade as a
        # skinned/retargetable asset.
        mode = "AUTHORED_NODE_ANIMATED"
        animation_mode = "GLTF_NODE_TIMELINE"
    else:
        mode = "AUTHORED_STATIC"
        animation_mode = "NONE"
    try:
        # Keep nested third-party assets addressable from the QML root.  Using
        # only ``path.name`` would flatten a texture/model pack and make the
        # snapshot claim a path that the RuntimeLoader cannot resolve.
        relative_source = path.relative_to(PROJECT_ROOT / "qml").as_posix()
    except ValueError:
        # This branch is retained for test fixtures or future local roots that
        # are admitted without living below the normal QML asset directory.
        relative_source = "assets/" + path.name
    return {
        "schema": SCHEMA,
        "id": str(asset_id),
        "status": "READY",
        "mode": mode,
        "source": path.as_uri(),
        "relative_source": relative_source,
        # Simulation entity Y is the stable avatar anchor used by the preview
        # mesh (roughly the hip/root).  Authored character files conventionally
        # place their local origin at the feet, so this keeps the fixture's
        # feet on the same terrain sample without changing physics or camera.
        "root_offset_m": -0.65,
        "format": "GLTF2",
        "skinned": skinned,
        "animation_mode": animation_mode,
        "skeleton": {
            "skins": len(skins),
            "joints": joint_count,
            "skinned_primitives": skinned_primitives,
        },
        "meshes": len(meshes),
        "primitives": primitive_count,
        "vertices": vertex_count,
        "animations": len(clips),
        "clips": clips,
        "bytes": len(source_bytes),
        "referenced_bytes": referenced_bytes,
        "attachment_sockets": _extract_attachment_sockets(nodes),
        "budget": {
            "max_source_bytes": MAX_SOURCE_BYTES,
            "max_referenced_bytes": MAX_REFERENCED_BYTES,
            "max_authored_instances": MAX_AUTHORED_INSTANCES,
        },
        "error": None,
    }


def inspect_asset(source: Any, asset_id: str | None = None) -> dict[str, Any]:
    """Validate one allowlisted local glTF/GLB and return its manifest view."""
    requested = str(source or "")
    path, error_code = _resolve_local_source(source)
    resolved_id = str(asset_id or (_asset_id_for_path(path) if path else "unknown-asset"))
    if error_code or path is None:
        return _error(resolved_id, error_code or "ASSET_SOURCE_INVALID", "Asset source is not an allowlisted local glTF file.", source=requested)
    try:
        if not path.is_file():
            return _error(resolved_id, "ASSET_SOURCE_MISSING", "The authored asset file does not exist.", source=requested)
    except OSError:
        return _error(resolved_id, "ASSET_SOURCE_UNREADABLE", "The authored asset file cannot be inspected.", source=requested)
    document, source_bytes, read_error = _read_json_document(path)
    if read_error or document is None:
        return _error(resolved_id, read_error or "GLTF_DOCUMENT_INVALID", "The glTF document could not be read.", source=requested)
    return _validate_document(path, source_bytes, document, resolved_id)


def _inspect_static_item_asset(
    asset_id: str,
    spec: dict[str, Any],
) -> dict[str, Any]:
    """Inspect one item mesh and keep skinned files out of item slots."""
    view = inspect_asset(spec.get("source"), asset_id)
    unit_scale = spec.get("unit_scale", (1.0, 1.0, 1.0))
    if not isinstance(unit_scale, (list, tuple)) or len(unit_scale) != 3:
        unit_scale = (1.0, 1.0, 1.0)
    safe_scale: list[float] = []
    for value in unit_scale:
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = 1.0
        safe_scale.append(round(number if math.isfinite(number) and number > 0.0 else 1.0, 4))
    view["unit_scale"] = safe_scale
    if isinstance(spec.get("weapon_fx"), dict):
        view["weapon_fx"] = copy.deepcopy(spec["weapon_fx"])
    if isinstance(view.get("budget"), dict):
        view["budget"]["max_authored_item_instances"] = MAX_AUTHORED_ITEM_INSTANCES
    if view.get("status") == "READY" and view.get("skinned"):
        view = copy.deepcopy(view)
        view["status"] = "ERROR"
        view["mode"] = "PRIMITIVE_FALLBACK"
        view["source"] = ""
        view["error"] = {
            "code": "ITEM_SKIN_UNEXPECTED",
            "message": "Static item slots do not admit skinned character assets.",
        }
        view["unit_scale"] = safe_scale
    return view


def procedural_character_asset() -> dict[str, Any]:
    """Describe the original runtime-generated crowd mesh as a real asset.

    It has no file URI by design: the geometry is built from the renderer's
    stable code contract and cached by pose bucket.  Calling it ``READY`` is
    not a placeholder claim; it means the runtime geometry and its material
    attributes are available before the QML scene is created.
    """
    return {
        "schema": SCHEMA,
        "id": PROCEDURAL_CHARACTER_ASSET_ID,
        "status": "READY",
        "mode": PROCEDURAL_CHARACTER_MODE,
        "source": "",
        "relative_source": "",
        "root_offset_m": -0.65,
        "format": "QQUICK3D_GEOMETRY",
        "skinned": False,
        "animation_mode": "FIXED_STEP_POSE_BUCKETS",
        "skeleton": {
            "skins": 0,
            "joints": 0,
            "skinned_primitives": 0,
        },
        "meshes": 1,
        "primitives": 1,
        "vertices": PROCEDURAL_CHARACTER_VERTEX_RECORDS,
        "triangles": PROCEDURAL_CHARACTER_TRIANGLES,
        "animations": 4,
        "clips": [
            {"name": "Idle", "duration_s": 0.0},
            {"name": "Walk", "duration_s": 0.0},
            {"name": "Sprint", "duration_s": 0.0},
            {"name": "Air", "duration_s": 0.0},
        ],
        "bytes": (
            PROCEDURAL_CHARACTER_VERTEX_RECORDS * PROCEDURAL_CHARACTER_VERTEX_STRIDE
            + PROCEDURAL_CHARACTER_TRIANGLES * 3 * 2
        ),
        "referenced_bytes": 0,
        "budget": {
            "max_source_bytes": MAX_SOURCE_BYTES,
            "max_referenced_bytes": MAX_REFERENCED_BYTES,
            "max_authored_instances": MAX_AUTHORED_INSTANCES,
        },
        "geometry": {
            "vertex_stride": PROCEDURAL_CHARACTER_VERTEX_STRIDE,
            "vertex_color": True,
            "pose_variants": PROCEDURAL_CHARACTER_POSE_VARIANTS,
        },
        "style": dict(CHARACTER_STYLE_CONTRACT),
        "attachment_sockets": {},
        "license": "ORIGINAL_RUNTIME_GENERATED",
        "error": None,
    }


def procedural_item_asset(asset_id: Any, item_kind: Any = "ITEM") -> dict[str, Any]:
    """Describe one native item-family mesh available before authored import.

    The returned record is intentionally a real renderer binding: the host
    resolves ``geometry_key`` to a cached ``QQuick3DGeometry`` object.  It is
    not a claim that an external file exists, and it does not hide a failed
    loader behind a fake success state.
    """
    wanted = str(asset_id or "item.unknown").strip()[:96] or "item.unknown"
    kind = str(item_kind or "ITEM").strip().upper()[:32] or "ITEM"
    return {
        "schema": SCHEMA,
        "id": wanted,
        "asset_id": wanted,
        "geometry_key": wanted,
        "asset_class": kind,
        "status": "READY",
        "mode": PROCEDURAL_ASSET_MODE,
        "source": "",
        "relative_source": "",
        "unit_scale": [1.0, 1.0, 1.0],
        "format": "QQUICK3D_GEOMETRY",
        "skinned": False,
        "animation_mode": "STATIC_STATEFUL_PRESENTATION",
        "meshes": 1,
        "primitives": 1,
        "geometry": {
            "vertex_stride": PROCEDURAL_ASSET_VERTEX_STRIDE,
            "vertex_color": True,
            "cache": "BOUNDED_ASSET_FAMILY",
            "topology": "INDEXED_TRIANGLES",
            "runtime_resolved": True,
            "budget": {
                "max_vertex_records": 4096,
                "max_triangles": 4096,
            },
        },
        "style": dict(ASSET_KIT_STYLE_CONTRACT),
        "license": "ORIGINAL_RUNTIME_GENERATED",
        "error": None,
    }


def _world_prop_variant(entity_id: Any) -> int:
    """Derive one stable prop silhouette without consulting render state."""
    digits = "".join(character for character in str(entity_id or "") if character.isdigit())
    try:
        return int(digits or "0") % 4
    except ValueError:
        return 0


def _authored_world_prop_binding(
    geometry_key: str,
    asset_class: str,
    source_key: str,
    variant: int,
) -> dict[str, Any] | None:
    source_name = str(source_key or "").strip().upper()
    variants = AUTHORED_WORLD_VARIANTS.get(source_name, ())
    selected_variant = int(variant) % len(variants) if variants else 0
    authored = (
        variants[selected_variant]
        if variants
        else AUTHORED_WORLD_SOURCES.get(source_name)
    )
    authored_path = authored.get("source") if isinstance(authored, dict) else None
    if not isinstance(authored_path, Path) or not authored_path.is_file():
        return None
    try:
        relative_source = authored_path.relative_to(PROJECT_ROOT / "qml").as_posix()
    except ValueError:
        relative_source = "assets/" + authored_path.name
    result = {
        "schema": SCHEMA,
        "id": geometry_key,
        "asset_id": str(authored.get("asset_id") or geometry_key),
        "geometry_key": geometry_key,
        "asset_class": asset_class,
        "variant": selected_variant if variants else int(variant) % 4,
        "mode": "AUTHORED_STATIC",
        "status": "READY",
        "source": authored_path.as_uri(),
        "relative_source": relative_source,
        "anchor": str(authored.get("anchor") or "FEET"),
        "height_m": float(authored.get("height_m") or 2.0),
        "unit_scale": [1.0, 1.0, 1.0],
        "style_id": str(authored.get("style_id") or PROCEDURAL_ASSET_STYLE_ID),
        "style": dict(ASSET_KIT_STYLE_CONTRACT),
        "format": "GLB",
        "state": "WORLD",
        "license": "ORIGINAL_BLENDER_AUTHORED",
        "error": None,
    }
    return result if variants else _art_variant(result,int(variant)%4)


def world_prop_asset(entity_kind: Any, entity_id: Any = "") -> dict[str, Any]:
    """Describe one world asset family for the native geometry renderer.

    World props are simulation entities, so their visual identity belongs in
    the same snapshot as position, scale and collision state.  The renderer
    can then select a cached geometry family from authored data instead of
    inferring a primitive from a QML fallback or from an entity id alone.
    """
    wanted = str(entity_kind or "PROP").strip().upper()
    variant = _world_prop_variant(entity_id)
    if 'ROCK' in wanted or 'BOULDER' in wanted:
        import hashlib
        variant=int.from_bytes(hashlib.blake2s(str(entity_id).encode(),digest_size=4).digest(),'little')%36
    if "RAMP" in wanted:
        geometry_key = "world.ramp"
        asset_class = "RAMP"
        variant = 0
    elif any(token in wanted for token in ("HOUSE", "BUILDING", "STRUCTURE", "HUT")):
        geometry_key = "world.stilt_hut"
        asset_class = "HOUSE"
        authored = _authored_world_prop_binding(
            geometry_key,
            asset_class,
            "HOUSE",
            variant,
        )
        if authored is not None:
            return authored
    elif "ROCK" in wanted or "BOULDER" in wanted:
        geometry_key = "world.prop.rock"
        asset_class = "ROCK"
    elif "MANGROVE" in wanted:
        geometry_key = "world.prop.mangrove"
        asset_class = "MANGROVE"
        authored = _authored_world_prop_binding(
            geometry_key,
            asset_class,
            "MANGROVE",
            variant,
        )
        if authored is not None:
            return authored
    elif "PALM" in wanted or "TREE" in wanted:
        geometry_key = "world.palm"
        asset_class = "PALM"
        authored = _authored_world_prop_binding(
            geometry_key,
            asset_class,
            "PALM",
            variant,
        )
        if authored is not None:
            return authored
    elif "DOCK" in wanted or "PIER" in wanted:
        geometry_key = "world.dock"
        asset_class = "DOCK"
        authored = _authored_world_prop_binding(
            geometry_key,
            asset_class,
            "DOCK",
            variant,
        )
        if authored is not None:
            return authored
        variant = 0
    elif "WINDMILL" in wanted:
        geometry_key = "world.windmill"
        asset_class = "WINDMILL"
        variant = 0
        authored = _authored_world_prop_binding(
            geometry_key,
            asset_class,
            "WINDMILL",
            variant,
        )
        if authored is not None:
            return authored
    elif "WATER_WHEEL" in wanted or "WATERWHEEL" in wanted:
        geometry_key = "world.water_wheel"
        asset_class = "WATER_WHEEL"
        variant = 0
        authored = _authored_world_prop_binding(
            geometry_key,
            asset_class,
            "WATER_WHEEL",
            variant,
        )
        if authored is not None:
            return authored
    elif "TIDE_BEACON" in wanted:
        geometry_key = "world.prop.shrine"
        asset_class = "TIDE_BEACON"
        variant = 0
        authored = _authored_world_prop_binding(
            geometry_key,
            asset_class,
            "TIDE_BEACON",
            variant,
        )
        if authored is not None:
            return authored
    elif wanted in {"SETTLEMENT_ROADS", "SETTLEMENT_FENCES"}:
        geometry_key = "world." + wanted.lower()
        asset_class = wanted
        variant = 0
    elif "PATH" in wanted or "TRAIL" in wanted:
        geometry_key = "world.path"
        asset_class = "PATH"
        variant = 0
    elif "BRIDGE" in wanted or "BOARDWALK" in wanted:
        geometry_key = "world.bridge"
        asset_class = "BRIDGE"
        variant = 0
    elif "FISH_RACK" in wanted or "FISHING_RACK" in wanted:
        geometry_key = "world.fish_rack"
        asset_class = "FISH_RACK"
        variant = 0
    elif "STALL" in wanted or "MARKET" in wanted:
        geometry_key = "world.market_stall"
        asset_class = "MARKET_STALL"
        variant = 0
    elif "BOAT" in wanted or "CANOE" in wanted:
        geometry_key = "world.boat"
        asset_class = "BOAT"
        variant = 0
    elif "BARREL" in wanted or "KEG" in wanted:
        geometry_key = "world.prop.barrel"
        asset_class = "BARREL"
        variant = 3
    elif "ROCK" in wanted or "BOULDER" in wanted:
        geometry_key = "world.prop.rock"
        asset_class = "ROCK"
    elif "TOTEM" in wanted or "SHRINE" in wanted:
        geometry_key = "world.totem"
        asset_class = "TOTEM"
        variant = 0
    elif "LIGHT" in wanted or "LANTERN" in wanted:
        geometry_key = "world.lantern"
        asset_class = "LANTERN"
        variant = 0
        authored = _authored_world_prop_binding(
            geometry_key,
            asset_class,
            "LANTERN",
            variant,
        )
        if authored is not None:
            return authored
    elif "SPAWN" in wanted:
        geometry_key = "world.spawn_marker"
        asset_class = "SPAWN_MARKER"
        variant = 0
    elif "STRESS" in wanted:
        geometry_key = "world.stress_pebble"
        asset_class = "STRESS_PROP"
        variant = 0
    else:
        geometry_key = WORLD_PROP_ASSET_FAMILIES[variant]
        asset_class = "PROP"
        if geometry_key=='world.prop.rock':
            import hashlib
            variant=int.from_bytes(hashlib.blake2s(str(entity_id).encode(),digest_size=4).digest(),'little')%36
    return {
        "schema": SCHEMA,
        "id": geometry_key,
        "asset_id": geometry_key,
        "geometry_key": geometry_key,
        "asset_class": asset_class,
        "variant": variant,
        "mode": PROCEDURAL_ASSET_MODE,
        "status": "READY",
        "source": "",
        "unit_scale": [1.0, 1.0, 1.0],
        "style_id": PROCEDURAL_ASSET_STYLE_ID,
        "style": dict(ASSET_KIT_STYLE_CONTRACT),
        "format": "QQUICK3D_GEOMETRY",
        "state": "WORLD",
        "license": "ORIGINAL_RUNTIME_GENERATED",
        "error": None,
    }


def default_catalog() -> dict[str, Any]:
    """Return the stable catalog exposed by the runtime snapshot."""
    blender_characters = {
        asset_id: inspect_asset(source, asset_id)
        for asset_id, source in BLENDER_CHARACTER_SOURCES.items()
    }
    selected = blender_characters[DEFAULT_CHARACTER_ASSET_ID]
    # The default character slot specifically requires skinning.  A valid but
    # static file is still reported, but is not allowed to replace the preview.
    if selected.get("status") == "READY" and not selected.get("skinned"):
        selected = copy.deepcopy(selected)
        selected["status"] = "ERROR"
        selected["mode"] = "PREVIEW_FALLBACK"
        selected["source"] = ""
        selected["error"] = {
            "code": "CHARACTER_SKIN_MISSING",
            "message": "The default character asset must contain a skin and JOINTS_0/WEIGHTS_0.",
        }
    crowd_variants = [
        blender_characters[asset_id]
        for asset_id in CROWD_CHARACTER_VARIANT_IDS
        if (
            blender_characters.get(asset_id, {}).get("status") == "READY"
            and blender_characters.get(asset_id, {}).get("skinned")
        )
    ]
    crowd_lod_variants = [
        inspected
        for asset_id, source in CROWD_LOD_SOURCES.items()
        for inspected in [inspect_asset(source, asset_id)]
        if inspected.get("status") == "READY"
        and inspected.get("skinned")
        and inspected.get("skeleton", {}).get("joints", MAX_JOINTS) <= MAX_CROWD_JOINTS
    ]
    crowd_selected = (
        crowd_variants[0]
        if crowd_variants
        else procedural_character_asset()
    )
    cast: dict[str, dict[str, Any]] = {}
    for role, (asset_id, source) in CAST_CHARACTER_SOURCES.items():
        view = blender_characters.get(asset_id) or inspect_asset(source, asset_id)
        if view.get("status") == "READY" and view.get("skinned"):
            cast[role] = view
    static_items = {
        asset_id: _inspect_static_item_asset(asset_id, spec)
        for asset_id, spec in DEFAULT_STATIC_ITEM_ASSET_SPECS.items()
    }
    return {
        "schema": SCHEMA,
        "policy": "ALLOWLISTED_LOCAL_GLTF2_RUNTIME_LOADER",
        "selected": selected,
        "cast": cast,
        "crowd_selected": crowd_selected,
        "crowd_variants": crowd_variants,
        "crowd_lod_variants": crowd_lod_variants,
        "crowd_visual": {
            "policy": "ORIGINAL_GG_BLENDER_CODEX_CROWD",
            "driver": "BLENDER_SKINNED_GLTF_WITH_FIXED_STEP_CLIPS",
            "license": "USER_AUTHORED_GG_BLENDER_ASSETS",
            "source_url": "",
            "reference_sources": [],
            "reference_policy": "ORIGINAL_GG_BLENDER_MODELS_ONLY",
            "variants": [row.get("id", "") for row in crowd_variants],
            "max_active_full_rigs": MAX_AUTHORED_INSTANCES,
            "max_active_models": (
                MAX_AUTHORED_CROWD_INSTANCES
                if crowd_lod_variants else MAX_AUTHORED_INSTANCES
            ),
            "lod_variants": [row.get("id", "") for row in crowd_lod_variants],
        },
        "character_style": dict(CHARACTER_STYLE_CONTRACT),
        "asset_kit": dict(ASSET_KIT_STYLE_CONTRACT),
        "procedural_asset_budget": PROCEDURAL_ASSET_MAX_FAMILIES,
        "instance_budget": MAX_AUTHORED_INSTANCES,
        "crowd_instance_budget": (
            MAX_AUTHORED_CROWD_INSTANCES
            if crowd_lod_variants else MAX_AUTHORED_INSTANCES
        ),
        "static_items": static_items,
        "item_instance_budget": MAX_AUTHORED_ITEM_INSTANCES,
        "fallback": {
            "mode": CHARACTER_VISUAL_FALLBACK,
            "reason": "One shared low-poly character geometry stays visible until the authored model has real visual children.",
        },
        "character_visual": {
            "policy": CHARACTER_VISUAL_POLICY,
            "preferred": CHARACTER_VISUAL_PREFERRED,
            "fallback": CHARACTER_VISUAL_FALLBACK,
            "max_active_models_per_character": 1,
        },
        "clip_contract": dict(CLIP_BY_MOTION_STATE),
    }


def extend_static_items(
    catalog: dict[str, Any],
    specs: Any,
) -> dict[str, Any]:
    """Admit additional local static meshes for an activated content page."""
    result = copy.deepcopy(catalog) if isinstance(catalog, dict) else default_catalog()
    static_items = result.setdefault("static_items", {})
    if not isinstance(static_items, dict):
        static_items = {}
        result["static_items"] = static_items
    if not isinstance(specs, dict):
        return result
    for asset_id, raw_spec in list(specs.items())[:MAX_STATIC_ITEM_DEFINITIONS]:
        if not isinstance(raw_spec, dict):
            continue
        wanted = str(asset_id or "").strip()[:96]
        if not wanted:
            continue
        static_items[wanted] = _inspect_static_item_asset(wanted, raw_spec)
    result["static_items"] = dict(list(static_items.items())[:MAX_STATIC_ITEM_DEFINITIONS])
    result["item_instance_budget"] = MAX_AUTHORED_ITEM_INSTANCES
    return result


def _art_variant(selected: dict[str,Any],variant: int) -> dict[str,Any]:
    """Select a compiled silhouette; admission counts/rig/budget stay unchanged."""
    if not variant or not selected.get('source'):return selected
    from backend.platform_support import local_file_path
    path=local_file_path(str(selected['source']))
    if path.suffix!='.glb':return selected
    candidate=ASSET_ROOT/'authored/variants'/path.parent.name/(path.stem+f'-v{variant}.glb')
    if not candidate.is_file():return selected
    result=dict(selected);result['source']=candidate.as_uri()
    result['relative_source']=str(candidate.relative_to(ASSET_ROOT));result['art_variant']=variant
    return result


def entity_binding(
    catalog: dict[str, Any],
    motion_state: Any,
    phase: Any,
    instance_rank: int,
    *,
    asset_role: str = "DEFAULT",
    variant_index: int | None = None,
    clip_override: str = "",
) -> dict[str, Any]:
    """Map one simulation pose to an authored asset slot or explicit fallback."""
    state = str(motion_state or "IDLE").strip().upper()
    if state not in CLIP_BY_MOTION_STATE:
        state = "IDLE"
    try:
        safe_phase = float(phase)
    except (TypeError, ValueError):
        safe_phase = 0.0
    if not math.isfinite(safe_phase):
        safe_phase = 0.0
    safe_phase = math.fmod(safe_phase, math.tau)
    if safe_phase < 0.0:
        safe_phase += math.tau
    runtime_clip = ""
    selected = catalog.get("selected") if isinstance(catalog, dict) else None
    role = str(asset_role or "DEFAULT").upper()
    if isinstance(catalog, dict) and isinstance(catalog.get("cast"), dict):
        cast_row = catalog["cast"].get(role)
        if isinstance(cast_row, dict) and cast_row.get("status") == "READY":
            selected = cast_row
    if role == "CROWD":
        crowd_variants = catalog.get("crowd_variants") if isinstance(catalog, dict) else None
        ready_variants = [
            row
            for row in crowd_variants
            if isinstance(row, dict) and row.get("status") == "READY"
        ] if isinstance(crowd_variants, list) else []
        try:
            variant_rank = int(instance_rank)
        except (TypeError, ValueError):
            variant_rank = 0
        appearance=variant_rank if variant_index is None else max(0,int(variant_index))
        if ready_variants:
            selected = ready_variants[max(0, appearance) % len(ready_variants)]
        crowd_selected = catalog.get("crowd_selected") if isinstance(catalog, dict) else None
        if not ready_variants and isinstance(crowd_selected, dict):
            selected = crowd_selected
        if variant_rank >= MAX_AUTHORED_INSTANCES:
            lod_variants = catalog.get("crowd_lod_variants") if isinstance(catalog, dict) else None
            ready_lod = [
                row for row in lod_variants
                if isinstance(row, dict)
                and row.get("status") == "READY"
                and row.get("skinned")
                and row.get("skeleton", {}).get("joints", MAX_JOINTS) <= MAX_CROWD_JOINTS
            ] if isinstance(lod_variants, list) else []
            if ready_lod:
                lod=ready_lod[(variant_rank - MAX_AUTHORED_INSTANCES) % len(ready_lod)]
                if variant_index is not None:
                    lod=next((r for r in ready_lod if r.get('source')==selected.get('source')),ready_lod[appearance%len(ready_lod)])
                selected=lod
    budget = MAX_AUTHORED_INSTANCES
    if role == "CROWD" and variant_rank >= MAX_AUTHORED_INSTANCES:
        # A missing/invalid LOD asset cannot silently consume the high-detail
        # budget or force sixteen 90-joint imports into the render scene.
        lod_ids = set(CROWD_LOD_SOURCES)
        if isinstance(selected, dict) and selected.get("id") in lod_ids:
            budget = MAX_AUTHORED_CROWD_INSTANCES
        else:
            budget = MAX_AUTHORED_INSTANCES
    elif isinstance(catalog, dict):
        try:
            budget = max(0, min(MAX_AUTHORED_INSTANCES, int(catalog.get("instance_budget", budget))))
        except (TypeError, ValueError):
            budget = MAX_AUTHORED_INSTANCES
    try:
        rank = int(instance_rank)
    except (TypeError, ValueError):
        rank = -1
    ready = (
        isinstance(selected, dict)
        and selected.get("status") == "READY"
        and selected.get("mode") in {
            "AUTHORED_SKINNED",
            "AUTHORED_NODE_ANIMATED",
            PROCEDURAL_CHARACTER_MODE,
        }
    )
    in_budget = 0 <= rank < budget
    if role=='CROWD' and ready:
        selected=_art_variant(selected,(appearance//max(1,len(ready_variants)))%36)
    if ready and in_budget:
        source = str(selected.get("source", ""))
        mode = str(selected.get("mode", "AUTHORED_SKINNED"))
        error = None
        requested_clip = str(clip_override or CLIP_BY_MOTION_STATE[state]).strip()
        if len(requested_clip) > 48:
            requested_clip = CLIP_BY_MOTION_STATE[state]
        if mode == PROCEDURAL_CHARACTER_MODE:
            # The pose is generated from the same fixed-step state and phase;
            # it does not pretend to be a RuntimeLoader timeline clip.
            clip = requested_clip
            runtime_clip = ""
            clip_status = "PROCEDURAL_POSE"
        else:
            available_clips = {
                str(row.get("name", "")).casefold(): str(row.get("name", ""))
                for row in selected.get("clips", [])
                if isinstance(row, dict) and str(row.get("name", "")).strip()
            }
            runtime_clip = available_clips.get(requested_clip.casefold(), "")
            clip = requested_clip if runtime_clip else ""
            clip_status = "READY" if clip else "ROOT_POSE_ONLY"
            if not runtime_clip and requested_clip in ('Sit','Sleep','Kneel'):
                # These are GG static rig poses, separate from GLB timelines.
                clip=runtime_clip=requested_clip;clip_status='GG_STATIC_POSE'
    else:
        source = ""
        if ready and not in_budget and isinstance(selected, dict):
            mode = (
                "PROCEDURAL_BUDGET"
                if selected.get("mode") == PROCEDURAL_CHARACTER_MODE
                else "PREVIEW_BUDGET"
            )
        else:
            mode = "PREVIEW_FALLBACK"
        error = selected.get("error") if isinstance(selected, dict) else None
        clip = ""
        clip_status = "NOT_LOADED"
    try:
        root_offset_m = float(
            selected.get("root_offset_m", 0.0)
            if isinstance(selected, dict)
            else 0.0
        )
    except (TypeError, ValueError):
        root_offset_m = 0.0
    if not math.isfinite(root_offset_m):
        root_offset_m = 0.0
    return {
        "id": str(selected.get("id", DEFAULT_CHARACTER_ASSET_ID)) if isinstance(selected, dict) else DEFAULT_CHARACTER_ASSET_ID,
        "mode": mode,
        "source": source,
        "root_offset_m": round(root_offset_m, 4),
        "instance_rank": rank,
        "instance_budget": budget,
        "clip": clip,
        "runtime_clip": runtime_clip,
        "clip_status": clip_status,
        "animation_mode": str(
            selected.get("animation_mode", "NONE")
            if isinstance(selected, dict)
            else "NONE"
        ),
        "attachment_sockets": (
            dict(selected.get("attachment_sockets"))
            if (
                ready
                and in_budget
                and role == "DEFAULT"
                and isinstance(selected, dict)
                and isinstance(selected.get("attachment_sockets"), dict)
                and str(selected.get("mode", "")) == "AUTHORED_SKINNED"
            )
            else {}
        ),
        "style_id": str(
            selected.get("style", {}).get("id", "")
            if isinstance(selected, dict)
            and isinstance(selected.get("style"), dict)
            else ""
        ),
        "phase": round(safe_phase, 5),
        "error": error,
    }


def item_binding(
    catalog: dict[str, Any],
    asset_id: Any,
    instance_rank: int,
    item_kind: Any = "ITEM",
    *,appearance_index: int = 0,
) -> dict[str, Any]:
    """Bind a validated Blender item model, with bounded native geometry as fallback."""
    wanted = str(asset_id or "item.unknown").strip()[:96] or "item.unknown"
    kind = str(item_kind or "ITEM").strip().upper()[:32] or "ITEM"
    static_items = catalog.get("static_items") if isinstance(catalog, dict) else None
    selected = static_items.get(wanted) if isinstance(static_items, dict) else None
    if isinstance(selected,dict):selected=_art_variant(selected,int(appearance_index)%36)
    if wanted=='itemmesh.weapon_sword' and isinstance(selected,dict):
        from backend.game_engine_sword_designs import sword_effect
        effect=sword_effect(appearance_index)
        if effect:
            selected=dict(selected)
            selected['weapon_fx']=copy.deepcopy(selected.get('weapon_fx',{}))
            selected['weapon_fx']['authored']=copy.deepcopy(effect)
    if wanted in ('itemmesh.weapon_axe','itemmesh.weapon_shield') and isinstance(selected,dict):
        from backend.game_engine_shield_axe_designs import equipment_visual
        visual=equipment_visual(wanted.rsplit('_',1)[-1],appearance_index)
        if visual:
            selected=dict(selected)
            selected['appearance_name']=visual['name']
            for key in ('construction','wielding_reference','weapon_subtype'):
                if key in visual:selected[key]=visual[key]
            effect=visual.get('weapon_fx',{}).get('authored')
            if effect:
                selected['weapon_fx']=copy.deepcopy(selected.get('weapon_fx',{}))
                selected['weapon_fx']['authored']=copy.deepcopy(effect)
    if wanted=='itemmesh.weapon_pistol' and isinstance(selected,dict):
        from backend.game_engine_pistol_designs import pistol_visual
        visual=pistol_visual(appearance_index)
        if visual:
            selected=dict(selected)
            selected['appearance_name']=visual['name']
            for key in ('construction','weapon_subtype','muzzle_points','emissive_feature','wielding_reference'):
                if key in visual:selected[key]=copy.deepcopy(visual[key])
            effect=visual.get('weapon_fx',{}).get('authored')
            if effect:
                selected['weapon_fx']=copy.deepcopy(selected.get('weapon_fx',{}))
                selected['weapon_fx']['authored']=copy.deepcopy(effect)
    if wanted in ('itemmesh.weapon_wand','itemmesh.weapon_staff','itemmesh.weapon_mace','itemmesh.weapon_offhand') and isinstance(selected,dict):
        from backend.game_engine_caster_designs import equipment_visual
        visual=equipment_visual(wanted.rsplit('_',1)[-1],appearance_index)
        if visual:
            selected=dict(selected)
            selected['appearance_name']=visual['name']
            for key in ('construction','weapon_subtype','wielding_reference','emissive_feature','articulation'):
                if key in visual:selected[key]=copy.deepcopy(visual[key])
            selected['weapon_fx']=copy.deepcopy(selected.get('weapon_fx',{}))
            selected['weapon_fx']['authored']=copy.deepcopy(visual['weapon_fx']['authored'])
    budget = MAX_AUTHORED_ITEM_INSTANCES
    if isinstance(catalog, dict):
        try:
            budget = max(
                0,
                min(
                    MAX_AUTHORED_ITEM_INSTANCES,
                    int(catalog.get("item_instance_budget", budget)),
                ),
            )
        except (TypeError, ValueError):
            budget = MAX_AUTHORED_ITEM_INSTANCES
    try:
        rank = int(instance_rank)
    except (TypeError, ValueError):
        rank = -1
    if (
        isinstance(selected, dict)
        and str(selected.get("status", "")) == "READY"
        and str(selected.get("mode", "")) == "AUTHORED_STATIC"
        and str(selected.get("source", ""))
        and rank >= 0
        and rank < budget
    ):
        authored = copy.deepcopy(selected)
        authored.update(
            {
                "schema": SCHEMA,
                "asset_id": wanted,
                "geometry_key": wanted,
                "asset_class": kind,
                "id": wanted,
                "mode": "AUTHORED_STATIC",
                "status": "READY",
                "instance_rank": rank,
                "instance_budget": budget,
                "style_id": "GG_SANDOVER_LOW_POLY",
                "style": dict(ASSET_KIT_STYLE_CONTRACT),
                "license": "ORIGINAL_BLENDER_AUTHORED",
                "error": None,
            }
        )
        return authored
    native = procedural_item_asset(wanted, kind)
    binding = {
        "schema": SCHEMA,
        "asset_id": wanted,
        "geometry_key": wanted,
        "asset_class": kind,
        "id": wanted,
        "mode": PROCEDURAL_ASSET_MODE,
        "status": "READY",
        "source": "",
        "relative_source": "",
        "unit_scale": [1.0, 1.0, 1.0],
        "instance_rank": rank,
        "instance_budget": budget,
        "style_id": PROCEDURAL_ASSET_STYLE_ID,
        "style": dict(ASSET_KIT_STYLE_CONTRACT),
        "format": "QQUICK3D_GEOMETRY",
        "geometry": dict(native.get("geometry", {})),
        "weapon_fx": copy.deepcopy(selected.get("weapon_fx", {}))
            if isinstance(selected, dict) else {},
        "license": "ORIGINAL_RUNTIME_GENERATED",
        "error": None,
    }
    # Keep the validated file visible to inspectors without allowing it to
    # create a second live Model.  This makes promotion an explicit content
    # decision instead of an accidental per-item visual split.
    if isinstance(selected, dict):
        binding["authored_candidate"] = {
            "id": str(selected.get("id", wanted)),
            "status": str(selected.get("status", "ERROR")),
            "mode": str(selected.get("mode", "PREVIEW_FALLBACK")),
            "source": str(selected.get("source", "")),
        }
    return binding
