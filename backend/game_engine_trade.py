"""Bounded item-for-item trade rules for the GAME ENGINE.

Trade is a state transition over canonical item instances.  This module only
owns the versioned rule/shape contract; the runtime owns locking, proximity,
line-of-sight and the actual instance movement.  That keeps a future vendor,
player-to-player exchange or NPC barter table on the same atomic path.
"""

from __future__ import annotations

import copy
import math
from typing import Any


SCHEMA = "gg.game-engine.trade.v1"
VERSION = 1
MAX_ID_LENGTH = 64
MAX_HISTORY = 8
MAX_TEXT_LENGTH = 128

PLAYER_SOURCE_LOCATION = "INVENTORY"
NPC_SOURCE_LOCATION = "POCKET"
BLOCKED_TAGS = frozenset({"QUEST", "SOULBOUND", "NO_TRADE", "BOUND"})


def _text(value: Any, default: str = "", limit: int = MAX_ID_LENGTH) -> str:
    return str(value or default).strip()[:limit]


def normalize_request(
    npc_id: Any = "",
    give_instance_id: Any = "",
    receive_instance_id: Any = "",
) -> dict[str, Any]:
    """Normalize one bounded item-for-item request without executing it."""
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "npc_id": _text(npc_id),
        "give_instance_id": _text(give_instance_id),
        "receive_instance_id": _text(receive_instance_id),
        "policy": "ITEM_FOR_ITEM_WHOLE_INSTANCE",
    }


def tradeable_definition(definition: Any) -> tuple[bool, dict[str, Any]]:
    """Validate authored trade flags before any instance can move."""
    if not isinstance(definition, dict):
        return False, {"error": "TRADE_DEFINITION_MISSING"}
    kind = _text(definition.get("kind"), "ITEM", 32).upper()
    raw_tags = definition.get("tags", [])
    tags = {
        _text(value, limit=32).upper()
        for value in raw_tags[:16]
    } if isinstance(raw_tags, (list, tuple)) else set()
    if kind == "CONTAINER":
        return False, {"error": "TRADE_CONTAINER_FORBIDDEN", "kind": kind}
    if kind == "QUEST":
        return False, {"error": "TRADE_QUEST_FORBIDDEN", "kind": kind}
    blocked = sorted(tags & BLOCKED_TAGS)
    if blocked:
        return False, {"error": "TRADE_ITEM_BOUND", "tags": blocked}
    definition_id = _text(definition.get("id"), limit=MAX_ID_LENGTH)
    if not definition_id:
        return False, {"error": "TRADE_DEFINITION_ID_MISSING"}
    return True, {
        "definition_id": definition_id,
        "kind": kind,
        "tags": sorted(tags)[:8],
    }


def validate_offer(
    instance: Any,
    definition: Any,
    *,
    owner_id: str,
    location: str,
) -> tuple[bool, dict[str, Any]]:
    """Require an exact owner/location match for an offer instance."""
    if not isinstance(instance, dict) or not _text(instance.get("instance_id")):
        return False, {"error": "TRADE_INSTANCE_REQUIRED"}
    expected_owner = _text(owner_id)
    expected_location = _text(location, limit=32).upper()
    if _text(instance.get("owner_id")) != expected_owner:
        return False, {"error": "TRADE_INSTANCE_OWNERSHIP_REQUIRED"}
    if _text(instance.get("location"), limit=32).upper() != expected_location:
        return False, {"error": "TRADE_INSTANCE_LOCATION_INVALID", "expected": expected_location}
    quantity = instance.get("quantity", 1)
    try:
        safe_quantity = int(quantity)
    except (TypeError, ValueError, OverflowError):
        safe_quantity = 0
    if safe_quantity < 1:
        return False, {"error": "TRADE_INSTANCE_QUANTITY_INVALID"}
    if instance.get('bound_to'):return False,{'error':'TRADE_ITEM_BOUND'}
    return tradeable_definition(definition)


def normalize_result(result: Any) -> dict[str, Any]:
    """Keep the latest trade small and safe for QML and memory persistence."""
    if not isinstance(result, dict) or not any(
        result.get(key) for key in ("action", "npc_id", "give", "receive", "player_gave", "player_received")
    ):
        return {}
    try:
        distance = float(result.get("distance_m", 0.0))
    except (TypeError, ValueError, OverflowError):
        distance = 0.0
    if not math.isfinite(distance):
        distance = 0.0
    normalized: dict[str, Any] = {
        "schema": SCHEMA,
        "version": VERSION,
        "action": _text(result.get("action"), "TRADE", 24).upper(),
        "npc_id": _text(result.get("npc_id")),
        "distance_m": round(max(0.0, min(1000.0, distance)), 3),
        "policy": _text(result.get("policy"), "ITEM_FOR_ITEM_WHOLE_INSTANCE", 48),
    }
    for key in ("give", "receive", "player_gave", "player_received"):
        value = result.get(key)
        if isinstance(value, dict):
            normalized[key] = copy.deepcopy(value)
    if isinstance(result.get("interaction_count"), int):
        normalized["interaction_count"] = max(0, min(2_000_000_000, result["interaction_count"]))
    if isinstance(result.get("npc_gear_upgrade"), dict):
        normalized["npc_gear_upgrade"] = copy.deepcopy(result["npc_gear_upgrade"])
    if isinstance(result.get("npc_power"), dict):
        normalized["npc_power"] = copy.deepcopy(result["npc_power"])
    return normalized


def view(last: Any = None) -> dict[str, Any]:
    """Expose the latest trade; the event journal remains the full audit log."""
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "last": normalize_result(last),
        "policy": "ATOMIC_CANONICAL_INSTANCE_TRANSFER",
        "history_source": "AUTHORITATIVE_EVENT_JOURNAL",
        "supported": True,
    }


def restore(raw: Any) -> dict[str, Any]:
    """Restore one saved latest-trade row while applying the same bounds."""
    if isinstance(raw, dict) and isinstance(raw.get("last"), dict):
        return normalize_result(raw["last"])
    return normalize_result(raw)
