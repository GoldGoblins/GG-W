"""Data-only input and keybinding contract for the GAME ENGINE.

The default grammar uses W/S to move and A/D to turn in place. E interacts
with the nearest NPC or world item; Q and E are not movement defaults.
Bindings are compact data so QML, replays, a future native client and the
in-game editor can consume the same action names. There is no arbitrary
script execution in this layer.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


SCHEMA = "gg.game-engine.input.v2"
VERSION = 2
MODEL = "WOW_CLASSIC_THIRD_PERSON"


ACTION_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {"id":"POSTURE_TOGGLE","label":"Sit / stand","group":"MOVEMENT","default":["K"]},
    {"id":"SHEATH_TOGGLE","label":"Draw / stow weapons","group":"COMBAT","default":["J"]},
    {"id":"WALK_TOGGLE","label":"Walk / run","group":"MOVEMENT","default":["L"]},
    {"id":"AUTORUN_TOGGLE","label":"Autorun","group":"MOVEMENT","default":["P"]},
    {"id": "TARGET_NEXT", "label": "Cycle target (Shift reverses)",
     "group": "COMBAT", "default": ["TAB"]},
    {"id": "RELOAD_FIREARM", "label": "Reload firearms", "group": "COMBAT", "default": ["Y"]},
    {"id": "PRIMARY_ATTACK", "label": "Primary attack",
     "group": "COMBAT", "default": ["T"]},
    {
        "id": "MOVE_FORWARD",
        "label": "Move forward",
        "group": "MOVEMENT",
        "default": ["W", "UP"],
    },
    {
        "id": "MOVE_BACK",
        "label": "Move backward",
        "group": "MOVEMENT",
        "default": ["S", "DOWN"],
    },
    {
        "id": "TURN_LEFT",
        "label": "Turn left",
        "group": "MOVEMENT",
        "default": ["A", "LEFT"],
    },
    {
        "id": "TURN_RIGHT",
        "label": "Turn right",
        "group": "MOVEMENT",
        "default": ["D", "RIGHT"],
    },
    {
        "id": "STRAFE_LEFT",
        "label": "Strafe left",
        "group": "MOVEMENT",
        "default": [],
    },
    {
        "id": "STRAFE_RIGHT",
        "label": "Strafe right",
        "group": "MOVEMENT",
        "default": [],
    },
    {
        "id": "INTERACT",
        "label": "Interact",
        "group": "WORLD",
        "default": ["E"],
    },
    {
        "id": "GRAPPLE",
        "label": "Grappling hook",
        "group": "MOVEMENT",
        "default": ["Q"],
    },
    {
        "id": "JUMP",
        "label": "Jump",
        "group": "MOVEMENT",
        "default": ["SPACE"],
    },
    {
        "id": "SPRINT",
        "label": "Sprint",
        "group": "MOVEMENT",
        "default": ["SHIFT"],
    },
    {
        "id": "TOGGLE_FLIGHT",
        "label": "Take off / land",
        "group": "MOVEMENT",
        "default": ["G"],
    },
    {
        "id": "TOGGLE_HOVERBOARD",
        "label": "Toggle hoverboard",
        "group": "VEHICLES",
        "default": ["V"],
    },
    {
        "id": "MOUNT_BOAT",
        "label": "Board / leave skiff",
        "group": "VEHICLES",
        "default": ["B"],
    },
    {
        "id": "VERTICAL_UP",
        "label": "Swim / fly up",
        "group": "MOVEMENT",
        "default": ["R"],
    },
    {
        "id": "VERTICAL_DOWN",
        "label": "Swim / fly down",
        "group": "MOVEMENT",
        "default": ["F"],
    },
    {
        "id": "ABILITY_SURGE",
        "label": "Ability: Surge",
        "group": "ABILITIES",
        "default": ["Z"],
    },
    {
        "id": "ABILITY_UNDERTOW",
        "label": "Ability: Undertow",
        "group": "ABILITIES",
        "default": ["X"],
    },
    {
        "id": "ABILITY_SKY_LEAP",
        "label": "Ability: Sky Leap",
        "group": "ABILITIES",
        "default": ["C"],
    },
)

ACTION_IDS = tuple(row["id"] for row in ACTION_DEFINITIONS)
DEFAULT_BINDINGS = {
    row["id"]: tuple(row["default"])
    for row in ACTION_DEFINITIONS
}

_KEY_ALIASES = {
    "SPACEBAR": "SPACE",
    "RETURN": "ENTER",
    "ESC": "ESCAPE",
    "CTRL": "CONTROL",
    "OPTION": "ALT",
}
_SPECIAL_KEYS = {
    "SPACE",
    "SHIFT",
    "CONTROL",
    "ALT",
    "META",
    "TAB",
    "ENTER",
    "ESCAPE",
    "BACKSPACE",
    "DELETE",
    "UP",
    "DOWN",
    "LEFT",
    "RIGHT",
}
_STRAFE_ACTIONS = {"STRAFE_LEFT", "STRAFE_RIGHT"}
_INTERACTION_KEYS = {"Q", "E"}


def normalize_key(value: Any) -> str | None:
    """Normalize a QML/native key token without accepting executable data."""
    token = str(value or "").strip().upper()
    token = _KEY_ALIASES.get(token, token)
    if token in _SPECIAL_KEYS:
        return token
    if len(token) == 1 and (token.isalpha() or token.isdigit()):
        return token
    if token.startswith("F") and token[1:].isdigit():
        number = int(token[1:])
        if 1 <= number <= 24:
            return token
    return None


def _definition(action: Any) -> dict[str, Any] | None:
    wanted = str(action or "").strip().upper()
    for row in ACTION_DEFINITIONS:
        if row["id"] == wanted:
            return row
    return None


def new_bindings() -> dict[str, Any]:
    """Return a fresh default binding state."""
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "model": MODEL,
        "bindings": {
            action: list(keys) for action, keys in DEFAULT_BINDINGS.items()
        },
        "actions": [
            {
                "id": row["id"],
                "label": row["label"],
                "group": row["group"],
            }
            for row in ACTION_DEFINITIONS
        ],
        "policy": "UNIQUE_PRIMARY_KEYS_DATA_ONLY",
    }


def normalize_bindings(state: Any) -> dict[str, Any]:
    """Return a bounded, valid copy while preserving known custom bindings."""
    normalized = new_bindings()
    if not isinstance(state, dict):
        return normalized
    source = state.get("bindings", state)
    if not isinstance(source, dict):
        return normalized
    for action in ACTION_IDS:
        raw_keys = source.get(action)
        if isinstance(raw_keys, str):
            raw_keys = [raw_keys]
        if not isinstance(raw_keys, (list, tuple)):
            continue
        keys: list[str] = []
        for raw_key in raw_keys[:3]:
            key = normalize_key(raw_key)
            if (
                key
                and key not in keys
                and not (action in _STRAFE_ACTIONS and key in _INTERACTION_KEYS)
            ):
                keys.append(key)
        if action in _STRAFE_ACTIONS:
            normalized["bindings"][action] = keys
        elif keys or not raw_keys:
            # An explicit empty list is an intentional unbinding. Restoring
            # the default here would recreate collisions removed by set_binding.
            # Missing or invalid binding values still retain their defaults.
            normalized["bindings"][action] = keys
    # Migrate the accidentally shipped V attack binding. V belongs to the
    # board, including saves containing the conflicting old pair.
    attacks = normalized["bindings"]["PRIMARY_ATTACK"]
    if "V" in attacks:
        normalized["bindings"]["PRIMARY_ATTACK"] = [k for k in attacks if k != "V"] or ["T"]
        normalized["bindings"]["TOGGLE_HOVERBOARD"] = ["V"]
    return normalized


def set_binding(
    state: Any,
    action: Any,
    key: Any,
    *,
    slot: int = 0,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Assign one key and move it out of another action if necessary.

    Moving a key instead of allowing silent duplicate axes makes the editor
    predictable.  The previous alternate key remains when a primary binding
    is replaced, which keeps the arrow-key convenience intact.
    """
    normalized = normalize_bindings(state)
    definition = _definition(action)
    normalized_key = normalize_key(key)
    if definition is None:
        return normalized, {
            "ok": False,
            "error": "GAME_ENGINE_BINDING_ACTION_INVALID",
            "action": str(action or ""),
        }
    if normalized_key is None:
        return normalized, {
            "ok": False,
            "error": "GAME_ENGINE_BINDING_KEY_INVALID",
            "key": str(key or ""),
        }

    action_id = definition["id"]
    if action_id in _STRAFE_ACTIONS and normalized_key in _INTERACTION_KEYS:
        return normalized, {
            "ok": False,
            "error": "GAME_ENGINE_BINDING_RESERVED_FOR_INTERACTION",
            "action": action_id,
            "key": normalized_key,
        }
    try:
        safe_slot = max(0, min(2, int(slot)))
    except (TypeError, ValueError):
        safe_slot = 0

    for other_action, keys in normalized["bindings"].items():
        if other_action != action_id and normalized_key in keys:
            normalized["bindings"][other_action] = [
                other_key for other_key in keys if other_key != normalized_key
            ]
    keys = [
        existing for existing in normalized["bindings"][action_id]
        if existing != normalized_key
    ]
    safe_slot = min(safe_slot, len(keys))
    keys.insert(safe_slot, normalized_key)
    normalized["bindings"][action_id] = keys[:3]
    return normalized, {
        "ok": True,
        "action": action_id,
        "key": normalized_key,
        "slot": safe_slot,
    }


def action_for_key(state: Any, key: Any) -> list[str]:
    """Return matching actions for diagnostics and future input backends."""
    normalized_key = normalize_key(key)
    if not normalized_key:
        return []
    normalized = normalize_bindings(state)
    return [
        action
        for action, keys in normalized["bindings"].items()
        if normalized_key in keys
    ]


def summary(state: Any) -> dict[str, Any]:
    """Return a compact copy safe to expose in a render snapshot."""
    normalized = normalize_bindings(state)
    result = deepcopy(normalized)
    result["primary"] = {
        action: keys[0] if keys else ""
        for action, keys in normalized["bindings"].items()
    }
    return result
