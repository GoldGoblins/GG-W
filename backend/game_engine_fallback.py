"""Terminal-style fallback view built from the authoritative game snapshot.

The DOS presentation is intentionally a renderer, not a second game mode.
It receives the same bounded entity, terrain and player rows as the rich 3D
surface.  A graphics-stage failure can therefore hide QtQuick3D while fixed
step movement, inventory, NPC identity, loot, economy, progression and persistence continue to use
exactly the same data.

The cell frame is that picture.  Each column is a ray through the same
authored asset volumes the low-poly view instances, quantized to a glyph
plus a foreground and background color.  It is built on every snapshot, so
the terminal image is already there when the graphics stage is hidden.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote, urlparse


SCHEMA = "gg.game-engine.fallback.v1"
MODE = "DOS_2D"
MAX_ENTITIES = 96
MAX_TERRAIN_CELLS = 64
MAX_TERMINAL_LINES = 16
FRAME_COLS = 64
FRAME_ROWS = 28
FRAME_FAR_M = 42.0
FRAME_NEAR_M = 0.35
FRAME_FOV_RAD = math.radians(72.0)
FRAME_EYE_M = 1.55
_GLYPH_RAMP = " .:-=+*#%@"
_STAMPS: dict[str, dict[str, Any] | None] = {}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _text(value: Any, default: str = "", limit: int = 64) -> str:
    return str(value or default).strip()[:limit]


def _equip_glyph(slot: Any) -> str:
    wanted = _text(slot, "", 16).upper()
    return {
        "HEAD": "*",
        "CHEST": "[",
        "BACK": "b",
        "FEET": "f",
        "MAIN_HAND": "/",
        "OFF_HAND": "o",
        "RANGED": "}",
    }.get(wanted, "+")


def _glyph(row: dict[str, Any]) -> str:
    kind = _text(row.get("kind"), "PROP", 32).upper()
    if kind == "PLAYER":
        return "@"
    if kind == "NPC" or "NPC" in kind:
        return "G"
    if kind == "GROUND_ITEM":
        return "!"
    if kind == "CHEST":
        return "C"
    if kind == "RAMP":
        return "^"
    if kind == "PALM" or "TREE" in kind:
        return "Y"
    if kind == "HOUSE" or "HUT" in kind:
        return "A"
    if kind == "DOCK" or "PIER" in kind:
        return "="
    if kind == "TOTEM" or "SHRINE" in kind:
        return "T"
    if kind == "LIGHT" or "LANTERN" in kind:
        return "i"
    if kind == "PROP":
        return "*"
    return "."


def _terrain_glyph(row: dict[str, Any]) -> str:
    surface = _text(row.get("surface"), "LAND", 24).upper()
    biome = _text(row.get("biome"), "LAND", 32).upper()
    if surface == "WATER" or "WATER" in biome or "REEF" in biome:
        return "~"
    if "CLIFF" in biome:
        return "#"
    if "DEEP" in biome:
        return "~"
    return ","


def _position(row: dict[str, Any]) -> tuple[float, float]:
    return _safe_float(row.get("x")), _safe_float(row.get("z"))


def _hex_color(value: Any, default: str = "#8d684b") -> str:
    text = _text(value, default, 16)
    if len(text) == 7 and text.startswith("#"):
        try:
            int(text[1:], 16)
        except ValueError:
            return default
        return text.lower()
    return default


def _mix_black(color: str, amount: float) -> str:
    red = int(color[1:3], 16)
    green = int(color[3:5], 16)
    blue = int(color[5:7], 16)
    keep = max(0.0, min(1.0, 1.0 - amount))
    return "#{:02x}{:02x}{:02x}".format(
        int(red * keep),
        int(green * keep),
        int(blue * keep),
    )


def _asset_file(asset: dict[str, Any]) -> Path | None:
    source = _text(asset.get("source"), "", 512)
    if source.startswith("file:"):
        from backend.platform_support import local_file_path
        path = local_file_path(source)
        return path if path.is_file() else None
    relative = _text(asset.get("relative_source"), "", 256)
    if not relative:
        return None
    candidate = Path(__file__).resolve().parents[1] / "qml" / relative
    return candidate if candidate.is_file() else None


def _stamp_for_asset(asset: dict[str, Any]) -> dict[str, Any] | None:
    path = _asset_file(asset)
    if path is None:
        return None
    key = str(path)
    cached = _STAMPS.get(key)
    if key in _STAMPS:
        return cached
    try:
        from backend.game_engine_geometry import mesh_column_stamp

        stamp = mesh_column_stamp(path)
    except Exception:
        stamp = None
    _STAMPS[key] = stamp
    return stamp


def _box_stamp(height: float, half_x: float, half_z: float, color: str) -> dict[str, Any]:
    return {
        "min_x": -half_x,
        "max_x": half_x,
        "min_y": 0.0,
        "max_y": height,
        "min_z": -half_z,
        "max_z": half_z,
        "nx": 1,
        "nz": 1,
        "height": [max(0.2, height)],
        "color": [color],
    }


def _volume_for_row(row: dict[str, Any]) -> dict[str, Any] | None:
    kind = _text(row.get("kind"), "PROP", 32).upper()
    if kind == "PLAYER" or bool(row.get("hidden")):
        return None
    asset = row.get("asset") if isinstance(row.get("asset"), dict) else {}
    color = _hex_color(row.get("color"))
    stamp = _stamp_for_asset(asset)
    if stamp is None:
        height = _safe_float(asset.get("height_m"), 1.8 if kind in {"NPC", "ACTOR"} else 1.2)
        stamp = _box_stamp(max(0.4, height), 0.45, 0.45, color)
    return {
        "x": _safe_float(row.get("x")),
        "y": _safe_float(row.get("y")),
        "z": _safe_float(row.get("z")),
        "yaw": _safe_float(row.get("yaw")),
        "sx": max(0.05, abs(_safe_float(row.get("sx"), 1.0))),
        "sy": max(0.05, abs(_safe_float(row.get("sy"), 1.0))),
        "sz": max(0.05, abs(_safe_float(row.get("sz"), 1.0))),
        "stamp": stamp,
        "fallback_color": color,
    }


def _sample_stamp(
    stamp: dict[str, Any],
    local_x: float,
    local_z: float,
    fallback: str,
) -> tuple[float, str]:
    span_x = float(stamp["max_x"]) - float(stamp["min_x"])
    span_z = float(stamp["max_z"]) - float(stamp["min_z"])
    if span_x <= 1e-6 or span_z <= 1e-6:
        return 0.0, fallback
    unit_x = (local_x - float(stamp["min_x"])) / span_x
    unit_z = (local_z - float(stamp["min_z"])) / span_z
    if unit_x < 0.0 or unit_x > 1.0 or unit_z < 0.0 or unit_z > 1.0:
        return 0.0, fallback
    nx = int(stamp["nx"])
    nz = int(stamp["nz"])
    ix = min(nx - 1, int(unit_x * nx))
    iz = min(nz - 1, int(unit_z * nz))
    index = iz * nx + ix
    height = float(stamp["height"][index])
    color = _hex_color(stamp["color"][index], fallback)
    if color == "#000000":
        color = fallback
    return height, color


def _ray_hit(
    volume: dict[str, Any],
    origin_x: float,
    origin_z: float,
    direction_x: float,
    direction_z: float,
) -> tuple[float, float, float, str] | None:
    """Return world distance, bottom, top and color for one asset volume."""
    yaw = float(volume["yaw"])
    cosine = math.cos(yaw)
    sine = math.sin(yaw)
    dx = origin_x - float(volume["x"])
    dz = origin_z - float(volume["z"])
    local_origin_x = (dx * cosine - dz * sine) / float(volume["sx"])
    local_origin_z = (dx * sine + dz * cosine) / float(volume["sz"])
    local_dir_x = (direction_x * cosine - direction_z * sine) / float(volume["sx"])
    local_dir_z = (direction_x * sine + direction_z * cosine) / float(volume["sz"])
    stamp = volume["stamp"]
    slabs: list[tuple[float, float]] = []
    for origin, direction, lower, upper in (
        (local_origin_x, local_dir_x, float(stamp["min_x"]), float(stamp["max_x"])),
        (local_origin_z, local_dir_z, float(stamp["min_z"]), float(stamp["max_z"])),
    ):
        if abs(direction) < 1e-8:
            if origin < lower or origin > upper:
                return None
            continue
        inverse = 1.0 / direction
        enter = (lower - origin) * inverse
        leave = (upper - origin) * inverse
        if enter > leave:
            enter, leave = leave, enter
        slabs.append((enter, leave))
    if not slabs:
        return None
    enter = max(pair[0] for pair in slabs)
    leave = min(pair[1] for pair in slabs)
    if leave < enter or leave < FRAME_NEAR_M:
        return None
    start = max(enter, FRAME_NEAR_M)
    if start > FRAME_FAR_M:
        return None
    steps = 6
    span = max(0.0, min(leave, FRAME_FAR_M) - start)
    for step in range(steps):
        distance = start + span * ((step + 0.5) / steps)
        local_x = local_origin_x + local_dir_x * distance
        local_z = local_origin_z + local_dir_z * distance
        column_height, color = _sample_stamp(
            stamp,
            local_x,
            local_z,
            volume["fallback_color"],
        )
        if column_height <= 0.05:
            continue
        bottom = float(volume["y"]) + float(stamp["min_y"]) * float(volume["sy"])
        top = bottom + column_height * float(volume["sy"])
        return distance, bottom, top, color
    return None


def _ground_color(terrain_rows: Iterable[dict[str, Any]], x: float, z: float) -> str:
    best_distance = 1e9
    best = "#c4a574"
    for row in terrain_rows:
        if not isinstance(row, dict):
            continue
        center = row.get("center_m") if isinstance(row.get("center_m"), dict) else row
        dx = _safe_float(center.get("x")) - x
        dz = _safe_float(center.get("z")) - z
        distance = dx * dx + dz * dz
        if distance >= best_distance:
            continue
        best_distance = distance
        surface = _text(row.get("surface"), "LAND", 24).upper()
        biome = _text(row.get("biome"), "", 32).upper()
        if surface == "WATER" or "WATER" in biome or "REEF" in biome:
            best = "#1d6d78"
        elif "CLIFF" in biome or "ROCK" in biome:
            best = "#6e5340"
        else:
            best = "#c4a574"
    return best


def build_cell_frame(
    entity_rows: Iterable[dict[str, Any]] = (),
    terrain_rows: Iterable[dict[str, Any]] = (),
    *,
    player_x: Any = 0.0,
    player_y: Any = 0.0,
    player_z: Any = 0.0,
    player_yaw: Any = 0.0,
    cols: int = FRAME_COLS,
    rows: int = FRAME_ROWS,
) -> dict[str, Any]:
    """Project the current asset poses into one terminal cell buffer."""
    safe_cols = max(16, min(96, int(cols)))
    safe_rows = max(12, min(48, int(rows)))
    origin_x = _safe_float(player_x)
    origin_z = _safe_float(player_z)
    eye_y = _safe_float(player_y) + FRAME_EYE_M
    yaw = _safe_float(player_yaw)
    volumes: list[tuple[float, dict[str, Any]]] = []
    for row in list(entity_rows)[:MAX_ENTITIES]:
        if not isinstance(row, dict):
            continue
        volume = _volume_for_row(row)
        if volume is None:
            continue
        dx = float(volume["x"]) - origin_x
        dz = float(volume["z"]) - origin_z
        distance = dx * dx + dz * dz
        if distance > (FRAME_FAR_M + 8.0) ** 2:
            continue
        volumes.append((distance, volume))
    volumes.sort(key=lambda item: item[0])
    volumes = volumes[:48]
    ground = _ground_color(terrain_rows, origin_x, origin_z)
    sky = "#07141c"
    palette = [sky, _mix_black(ground, 0.45), ground]
    glyphs = [[" "] * safe_cols for _ in range(safe_rows)]
    fg_index = [[0] * safe_cols for _ in range(safe_rows)]
    bg_index = [[0] * safe_cols for _ in range(safe_rows)]

    def color_index(color: str) -> int:
        wanted = _hex_color(color, sky)
        if wanted in palette:
            return palette.index(wanted)
        if len(palette) >= 256:
            return 1
        palette.append(wanted)
        return len(palette) - 1

    ground_index = color_index(ground)
    ground_bg = color_index(_mix_black(ground, 0.55))
    horizon = int(safe_rows * 0.62)
    half_fov = FRAME_FOV_RAD * 0.5
    aspect = (safe_cols * 0.5) / safe_rows
    focal_y = (safe_rows * 0.5) * aspect / math.tan(half_fov)
    for column in range(safe_cols):
        offset = ((column + 0.5) / safe_cols * 2.0 - 1.0) * half_fov
        direction_x = math.sin(yaw + offset)
        direction_z = math.cos(yaw + offset)
        hits: list[tuple[float, float, float, str]] = []
        for _distance, volume in volumes:
            hit = _ray_hit(volume, origin_x, origin_z, direction_x, direction_z)
            if hit is not None:
                hits.append(hit)
        hits.sort(key=lambda item: item[0])
        filled = [False] * safe_rows
        for distance, bottom, top, color in hits:
            perp = max(FRAME_NEAR_M, distance * math.cos(offset))
            shade = 1.0 - min(1.0, perp / FRAME_FAR_M)
            glyph = _GLYPH_RAMP[min(len(_GLYPH_RAMP) - 1, int(shade * (len(_GLYPH_RAMP) - 1)))]
            if glyph == " ":
                glyph = "."
            foreground = color_index(color)
            background = color_index(_mix_black(color, 0.62))
            top_row = int(round(horizon - (top - eye_y) / perp * focal_y))
            bottom_row = int(round(horizon - (bottom - eye_y) / perp * focal_y))
            if bottom_row < top_row:
                top_row, bottom_row = bottom_row, top_row
            top_row = max(0, top_row)
            bottom_row = min(safe_rows - 1, bottom_row)
            for row_index in range(top_row, bottom_row + 1):
                if filled[row_index]:
                    continue
                glyphs[row_index][column] = glyph
                fg_index[row_index][column] = foreground
                bg_index[row_index][column] = background
                filled[row_index] = True
        for row_index in range(horizon, safe_rows):
            if filled[row_index]:
                continue
            glyphs[row_index][column] = "~" if ground == "#1d6d78" else "."
            fg_index[row_index][column] = ground_index
            bg_index[row_index][column] = ground_bg
    return {
        "renderer": "DOS_ASSET_COLUMNS",
        "source": "AUTHORED_ASSET_VOLUMES",
        "cols": safe_cols,
        "rows": safe_rows,
        "palette": palette,
        "glyphs": ["".join(row) for row in glyphs],
        "fg": ["".join(f"{value:02x}" for value in row) for row in fg_index],
        "bg": ["".join(f"{value:02x}" for value in row) for row in bg_index],
        "camera": {
            "x": round(origin_x, 3),
            "y": round(eye_y, 3),
            "z": round(origin_z, 3),
            "yaw": round(yaw, 4),
        },
    }


def build_view(
    entity_rows: Iterable[dict[str, Any]] = (),
    terrain_rows: Iterable[dict[str, Any]] = (),
    *,
    player_x: Any = 0.0,
    player_y: Any = 0.0,
    player_z: Any = 0.0,
    player_yaw: Any = 0.0,
    state: Any = "IDLE",
    tick: Any = 0,
    active_entities: Any = 0,
    active_particles: Any = 0,
    event_rows: Iterable[dict[str, Any]] = (),
    command: dict[str, Any] | None = None,
    equipment_rows: Iterable[dict[str, Any]] = (),
    economy: dict[str, Any] | None = None,
    combat: dict[str, Any] | None = None,
    quests: dict[str, Any] | None = None,
    factions: dict[str, Any] | None = None,
    dialogue: dict[str, Any] | None = None,
    social: dict[str, Any] | None = None,
    world_events: dict[str, Any] | None = None,
    radius_m: Any = 18.0,
) -> dict[str, Any]:
    """Build a bounded terminal map without inventing gameplay state."""
    safe_player_x = _safe_float(player_x)
    safe_player_y = _safe_float(player_y)
    safe_player_z = _safe_float(player_z)
    safe_player_yaw = _safe_float(player_yaw)
    safe_radius = max(6.0, min(256.0, _safe_float(radius_m, 18.0)))
    entity_rows = list(entity_rows)[:MAX_ENTITIES]
    terrain_rows = list(terrain_rows)[:MAX_TERRAIN_CELLS]

    entities: list[dict[str, Any]] = []
    for row in entity_rows:
        if not isinstance(row, dict):
            continue
        x, z = _position(row)
        individual = row.get("individual")
        if not isinstance(individual, dict):
            individual = {}
        kind = _text(row.get("kind"), "PROP", 32).upper()
        name = _text(individual.get("name"), row.get("id"), 64)
        raw_progression = individual.get("progression")
        progression = raw_progression if isinstance(raw_progression, dict) else {}
        npc_progression = {
            "level": max(1, int(_safe_float(progression.get("level"), 1))),
            "spec": _text(progression.get("spec"), "EXPLORER", 24).upper(),
            "ascension": max(0, int(_safe_float(progression.get("ascension"), 0))),
            "gear_score": round(max(0.0, _safe_float(progression.get("gear_score"))), 3),
            "power_score": round(max(0.0, _safe_float(progression.get("power_score"))), 3),
        }
        label = name
        if kind == "NPC" or "NPC" in kind:
            label = (
                f"{name} L{npc_progression['level']} "
                f"P{npc_progression['power_score']:.0f}"
            )[:64]
        equipment = row.get("equipment") if isinstance(row.get("equipment"), list) else []
        compact_equipment: list[dict[str, Any]] = []
        for item in equipment[:8]:
            if not isinstance(item, dict):
                continue
            slot = _text(item.get("equipped_slot"), "", 16).upper()
            attachment = item.get("attachment") if isinstance(item.get("attachment"), dict) else {}
            compact_equipment.append(
                {
                    "slot": slot,
                    "name": _text(item.get("name"), "", 32),
                    "socket": _text(attachment.get("socket"), slot, 16).upper(),
                    "glyph": _equip_glyph(slot),
                    "color": _text(
                        (item.get("visual") or {}).get("base_color")
                        if isinstance(item.get("visual"), dict)
                        else item.get("rarity_color"),
                        "#d6d6d6",
                        16,
                    ),
                }
            )
        entities.append(
            {
                "id": _text(row.get("id"), "entity-unknown", 96),
                "kind": kind,
                "x": round(x, 3),
                "z": round(z, 3),
                "glyph": _glyph(row),
                "color": _text(row.get("color"), "#8db89a", 16),
                "label": label,
                "equipment": compact_equipment,
                "state": _text(row.get("motion_state"), "STATIC", 32).upper(),
                "action": _text(
                    individual.get("action"),
                    row.get("world_action"),
                    32,
                ).upper(),
                "target_id": _text(
                    (individual.get("target") or {}).get("id")
                    if isinstance(individual.get("target"), dict)
                    else "",
                    "",
                    96,
                ),
                "progression": npc_progression,
            }
        )

    terrain: list[dict[str, Any]] = []
    for row in list(terrain_rows)[:MAX_TERRAIN_CELLS]:
        if not isinstance(row, dict):
            continue
        center = row.get("center_m")
        center = center if isinstance(center, dict) else row
        terrain.append(
            {
                "key": _text(row.get("key"), "cell-unknown", 64),
                "x": round(_safe_float(center.get("x")), 3),
                "z": round(_safe_float(center.get("z")), 3),
                "glyph": _terrain_glyph(row),
                "surface": _text(row.get("surface"), "LAND", 24).upper(),
                "biome": _text(row.get("biome"), "", 32).upper(),
            }
        )

    safe_state = _text(state, "IDLE", 24).upper()
    safe_tick = max(0, int(_safe_float(tick)))
    safe_active_entities = max(0, int(_safe_float(active_entities)))
    safe_active_particles = max(0, int(_safe_float(active_particles)))
    economy_view = economy if isinstance(economy, dict) else {}
    wallet = economy_view.get("wallet", {})
    wallet_gold = max(0, int(_safe_float(wallet.get("gold"), 0))) if isinstance(wallet, dict) else 0
    vendors = economy_view.get("vendors", [])
    first_vendor = vendors[0] if isinstance(vendors, list) and vendors else {}
    vendor_name = _text(first_vendor.get("name"), "NONE", 24) if isinstance(first_vendor, dict) else "NONE"
    vendor_presence = first_vendor.get("presence", {}) if isinstance(first_vendor, dict) else {}
    vendor_status = (
        "READY"
        if isinstance(vendor_presence, dict) and vendor_presence.get("available")
        else "OUT"
    )
    combat_view = combat if isinstance(combat, dict) else {}
    combat_actors = combat_view.get("actors", [])
    player_actor = next(
        (
            row
            for row in combat_actors
            if isinstance(row, dict) and str(row.get("id")) == "player"
        ),
        {},
    ) if isinstance(combat_actors, list) else {}
    quests_view = quests if isinstance(quests, dict) else {}
    factions_view = factions if isinstance(factions, dict) else {}
    dialogue_view = dialogue if isinstance(dialogue, dict) else {}
    social_view = social if isinstance(social, dict) else {}
    world_events_view = world_events if isinstance(world_events, dict) else {}
    faction_rows = factions_view.get("factions", [])
    player_faction = next(
        (
            row
            for row in faction_rows
            if isinstance(row, dict) and row.get("player_standing")
        ),
        faction_rows[0] if isinstance(faction_rows, list) and faction_rows else {},
    ) if isinstance(faction_rows, list) else {}
    health = max(0, int(_safe_float(player_actor.get("health"), 0)))
    max_health = max(0, int(_safe_float(player_actor.get("max_health"), 0)))
    quest_active = max(0, int(_safe_float(quests_view.get("active_count"), 0)))
    quest_ready = max(0, int(_safe_float(quests_view.get("ready"), 0)))
    faction_id = _text(player_faction.get("id"), "NONE", 24).upper()
    faction_standing = int(_safe_float(player_faction.get("player_standing"), 0))
    lines = [
        "GG//DOS FRONTIER",
        f"STATE {safe_state}  TICK {safe_tick}",
        f"ENT {safe_active_entities}  FX {safe_active_particles}",
        f"POS {safe_player_x:.1f},{safe_player_z:.1f}",
    ]
    gear_bits: list[str] = []
    for item in list(equipment_rows)[:6]:
        if not isinstance(item, dict):
            continue
        slot = _text(item.get("equipped_slot"), "", 8).upper()
        name = _text(item.get("name"), "", 18)
        if not slot and not name:
            continue
        gear_bits.append(f"{slot[:2] or _equip_glyph(slot)}:{name or slot}")
    if not gear_bits:
        player_row = next(
            (
                row
                for row in entities
                if isinstance(row, dict) and row.get("kind") == "PLAYER"
            ),
            {},
        )
        for item in (player_row.get("equipment") or [])[:6]:
            if not isinstance(item, dict):
                continue
            slot = _text(item.get("slot"), "", 8)
            name = _text(item.get("name"), "", 18)
            if slot or name:
                gear_bits.append(f"{slot[:2] or '+'}:{name or slot}")
    if gear_bits:
        lines.append("GEAR " + " ".join(gear_bits))
    lines.extend(
        [
            "@ YOU  G NPC  ! LOOT  C CACHE",
            "WASD MOVE  E INTERACT  I BAG",
            f"GOLD {wallet_gold}  SHOP {vendor_name} {vendor_status}",
            f"HP {health}/{max_health}  QUEST {quest_active} ACTIVE {quest_ready} READY",
            f"REP {faction_id} {faction_standing:+d}  COMBAT {str(player_actor.get('alive', True)).upper()}",
        ]
    )
    active_events = world_events_view.get("active", [])
    if isinstance(active_events, list) and active_events:
        first_event = active_events[0] if isinstance(active_events[0], dict) else {}
        lines.append(
            f"EVENT {_text(first_event.get('name'), 'WORLD EVENT', 28)} "
            f"{int(_safe_float((first_event.get('state') or {}).get('progress'), 0.0) * 100):02d}%"
        )
    dialogue_node = dialogue_view.get("node", {})
    dialogue_active = dialogue_view.get("active", {})
    if dialogue_view.get("open") and isinstance(dialogue_node, dict):
        speaker = _text(dialogue_node.get("speaker"), "NPC", 24)
        spoken = _text(dialogue_node.get("text"), "", 72)
        choices = dialogue_node.get("choices", [])
        choice_ids = "/".join(
            _text(choice.get("id"), limit=20)
            for choice in choices[:3]
            if isinstance(choice, dict) and choice.get("id")
        ) if isinstance(choices, list) else ""
        lines.append(
            f"TALK {_text(dialogue_active.get('npc_id'), 'NPC', 20)} "
            f"{speaker}: {spoken} {choice_ids}".strip()
        )
    recent_events: list[str] = []
    for raw_event in list(event_rows)[-3:]:
        if not isinstance(raw_event, dict):
            continue
        sequence = max(0, int(_safe_float(raw_event.get("sequence"), 0)))
        kind = _text(raw_event.get("kind"), "EVENT", 16).upper()
        text = _text(raw_event.get("text"), kind, 72)
        recent_events.append(f"{sequence:04d} {kind} {text}")
    last_command = command if isinstance(command, dict) else {}
    command_input = _text(last_command.get("input"), limit=48)
    command_message = _text(last_command.get("message"), limit=72)
    command_lines: list[str] = []
    if command_input:
        command_lines = [
            f"> {command_input}",
            f"{'OK' if last_command.get('ok') else 'ERR'} {command_message}",
        ]
    event_capacity = max(0, MAX_TERMINAL_LINES - len(lines) - len(command_lines))
    lines.extend(recent_events[-event_capacity:])
    lines.extend(command_lines)
    lines = lines[:MAX_TERMINAL_LINES]
    return {
        "schema": SCHEMA,
        "version": 1,
        "mode": MODE,
        "renderer": "QTQUICK_CANVAS_TERMINAL",
        "palette": {
            "background": "#030604",
            "grid": "#173117",
            "text": "#9fe3a4",
            "muted": "#5d9b66",
            "player": "#e3bd63",
            "water": "#4c9ca0",
        },
        "camera": {
            "center_x": round(safe_player_x, 3),
            "center_y": round(safe_player_y, 3),
            "center_z": round(safe_player_z, 3),
            "yaw": round(safe_player_yaw, 4),
            "radius_m": round(safe_radius, 3),
        },
        "frame": build_cell_frame(
            entity_rows,
            terrain_rows,
            player_x=safe_player_x,
            player_y=safe_player_y,
            player_z=safe_player_z,
            player_yaw=safe_player_yaw,
        ),
        "entities": entities,
        "terrain": terrain,
        "combat": dict(combat_view),
        "quests": dict(quests_view),
        "factions": dict(factions_view),
        "dialogue": dict(dialogue_view),
        "social": dict(social_view),
        "world_events": dict(world_events_view),
        "terminal": {
            "title": "GG//DOS FRONTIER",
            "prompt": ">",
            "lines": lines,
        },
        "command": dict(last_command),
        "shared_contract": "AUTHORITATIVE_FIXED_STEP_ENTITY_ITEM_NPC_DATA",
        "policy": "BOUNDED_2D_FALLBACK_RENDERER_NO_SIMULATION_MUTATION",
    }
