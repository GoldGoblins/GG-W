"""Deterministic progression and power evaluation for living NPCs.

NPC progression is a simulation contract, not a render-side badge.  It uses
the same XP curve as the player, stores level/stat/talent/ascension state on
the individual, and derives gear power from the canonical item instances that
are actually equipped.  The host is responsible for supplying those real
instances; this module never invents an item or silently upgrades a person.
"""

from __future__ import annotations

import copy
import math
from typing import Any, Iterable

from backend import game_engine_progression as shared_progression


SCHEMA = "gg.game-engine.npc.progression.v1"
VERSION = 1
MAX_LEVEL = shared_progression.MAX_LEVEL
MAX_ASCENSION = 12
MAX_PARAGON = 1_000_000
ASCENSION_PARAGON_COST = 8
ASCENSION_STAT_BONUS = 2
MAX_XP_GAIN = 1_000_000
MAX_STAT_VALUE = 100_000
MAX_DERIVED_STATS = 24
MAX_EQUIPPED_SUMMARY = 16
MAX_PROFESSIONS = 8
MAX_PROFESSION_LEVEL = 100

STAT_KEYS = ("might", "finesse", "spirit", "grit")
PROFESSION_KEYS = (
    "SURVIVAL",
    "BLACKSMITHING",
    "LEATHERWORKING",
    "JEWELCRAFTING",
    "ENCHANTING",
)

RARITY_RANK = {
    "TRASH": 0,
    "COMMON": 1,
    "UNCOMMON": 2,
    "RARE": 3,
    "EPIC": 4,
    "LEGENDARY": 5,
    "ARTIFACT": 6,
}
QUALITY_RANK = {
    "STANDARD": 0,
    "FINE": 1,
    "MASTERWORK": 2,
    "ARTIFACT": 3,
}

SPEC_WEIGHTS: dict[str, dict[str, int]] = {
    "EXPLORER": {"might": 1, "finesse": 4, "spirit": 3, "grit": 2},
    "WARDEN": {"might": 3, "finesse": 1, "spirit": 2, "grit": 4},
    "DUELIST": {"might": 4, "finesse": 3, "spirit": 1, "grit": 2},
}
TALENT_BY_SPEC = {
    "EXPLORER": "trailblazer",
    "WARDEN": "tidewalker",
    "DUELIST": "skybound",
}
ACTION_XP = {
    "OBSERVE_PLAYER": 1,
    "REST": 1,
    "SEEK_FOOD": 2,
    "SEEK_WATER": 2,
    "INSPECT_LOOT": 4,
    "EXPLORE": 3,
    "GATHER": 5,
    "HAUL": 5,
    "CRAFT": 12,
}
POSITIVE_ACTION_STATUSES = frozenset(
    {
        "COMMITTED",
        "CONSUMED",
        "REFILLED",
        "RESTED",
        "OBSERVED",
        "INSPECTED",
        "LOOTED",
        "EQUIPPED",
    }
)
GEAR_STAT_WEIGHTS = {
    "damage": 4.0,
    "damage_pct": 3.0,
    "armor": 3.0,
    "health": 1.5,
    "stamina": 1.5,
    "mana": 1.2,
    "spell_power": 2.0,
    "crit": 2.0,
    "loot_find": 1.7,
    "travel_speed": 1.0,
    "move_speed": 1.0,
    "swim_speed": 1.0,
    "damage_reduction": 2.0,
}


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _clamp(value: Any, low: float, high: float, default: float = 0.0) -> float:
    return max(low, min(high, _safe_float(value, default)))


def _text(value: Any, default: str = "", limit: int = 64) -> str:
    return str(value or default).strip()[:limit]


def _number(value: Any) -> int | float:
    number = _safe_float(value)
    return int(number) if number.is_integer() else round(number, 4)


def _stat_map(raw: Any, *, default: dict[str, Any] | None = None) -> dict[str, int | float]:
    source = raw if isinstance(raw, dict) else {}
    fallback = default if isinstance(default, dict) else {}
    result: dict[str, int | float] = {}
    keys = list(dict.fromkeys(list(fallback)[:MAX_DERIVED_STATS] + list(source)[:MAX_DERIVED_STATS]))
    for key in keys[:MAX_DERIVED_STATS]:
        wanted = _text(key, limit=48).lower()
        if not wanted:
            continue
        result[wanted] = _number(_clamp(
            source.get(key, fallback.get(key, 0.0)),
            -MAX_STAT_VALUE,
            MAX_STAT_VALUE,
        ))
    return result


def spec_for_identity(
    *,
    role: Any = "",
    archetype: Any = "",
    occupation: Any = "",
) -> str:
    values = {
        _text(role, limit=32).upper(),
        _text(archetype, limit=32).upper(),
        _text(occupation, limit=32).upper(),
    }
    if values.intersection({"WARDEN", "GUARDIAN", "BLACKSMITH", "LEATHERWORKER"}):
        return "WARDEN"
    if values.intersection({"DUELIST", "RAIDER", "HUNTER", "CRITTER"}):
        return "DUELIST"
    return "EXPLORER"


def starter_state(
    identity_id: Any = "",
    *,
    role: Any = "",
    archetype: Any = "",
    occupation: Any = "",
) -> dict[str, Any]:
    spec = spec_for_identity(role=role, archetype=archetype, occupation=occupation)
    weights = SPEC_WEIGHTS[spec]
    primary_talent = TALENT_BY_SPEC[spec]
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "identity_id": _text(identity_id, limit=64),
        "race": "ISLANDER",
        "class_id": f"npc.{_text(occupation, 'traveler', 32).lower()}",
        "spec": spec,
        "level": 1,
        "xp": 0,
        "xp_to_next": shared_progression.xp_for_next(1),
        "ascension": 0,
        "paragon": 0,
        "stat_points": 0,
        "talent_points": 0,
        "talents": {
            "trailblazer": 1 if primary_talent == "trailblazer" else 0,
            "tidewalker": 1 if primary_talent == "tidewalker" else 0,
            "skybound": 1 if primary_talent == "skybound" else 0,
        },
        "base_stats": {
            key: 5 + (1 if weights[key] >= 4 else 0)
            for key in STAT_KEYS
        },
        "additive_stats": {
            "move_speed": 0.0,
            "swim_speed": 0.0,
            "air_control": 0.0,
            "loot_find": 0.0,
        },
        "gear_stats": {},
        "derived_stats": {},
        "gear_score": 0.0,
        "power_score": 0.0,
        "equipped_count": 0,
        "equipped_items": [],
        "professions": {
            profession: {
                "level": 1,
                "xp": 0,
                "xp_to_next": 100,
            }
            for profession in PROFESSION_KEYS
        },
        "last_action_count": 0,
        "last_gain": {},
        "last_power_change": {},
        "revision": 0,
    }


def _normalize_professions(raw: Any, fallback: Any) -> dict[str, dict[str, int]]:
    source = raw if isinstance(raw, dict) else {}
    base = fallback if isinstance(fallback, dict) else {}
    result: dict[str, dict[str, int]] = {}
    for profession in PROFESSION_KEYS[:MAX_PROFESSIONS]:
        row = source.get(profession)
        if not isinstance(row, dict):
            row = base.get(profession) if isinstance(base.get(profession), dict) else {}
        level = max(1, min(MAX_PROFESSION_LEVEL, _safe_int(row.get("level"), 1)))
        xp = max(0, min(MAX_XP_GAIN, _safe_int(row.get("xp"), 0)))
        result[profession] = {
            "level": level,
            "xp": xp,
            "xp_to_next": 100 + (level - 1) * 50,
        }
    return result


def _normalize_event(raw: Any, *, limit: int = 48) -> dict[str, Any]:
    row = raw if isinstance(raw, dict) else {}
    return {
        "kind": _text(row.get("kind"), limit=24).upper(),
        "amount": max(0, min(MAX_XP_GAIN, _safe_int(row.get("amount"), 0))),
        "source": _text(row.get("source"), limit=limit),
        "item_id": _text(row.get("item_id"), limit=96),
        "time_s": round(max(0.0, _safe_float(row.get("time_s"))), 3),
        "level_ups": max(0, min(MAX_LEVEL, _safe_int(row.get("level_ups"), 0))),
        "ascension": max(0, min(MAX_ASCENSION, _safe_int(row.get("ascension"), 0))),
    }


def normalize_state(
    raw: Any,
    fallback: dict[str, Any] | None = None,
    *,
    identity_id: Any = "",
    role: Any = "",
    archetype: Any = "",
    occupation: Any = "",
) -> dict[str, Any]:
    seed = copy.deepcopy(fallback) if isinstance(fallback, dict) else starter_state(
        identity_id,
        role=role,
        archetype=archetype,
        occupation=occupation,
    )
    merged = copy.deepcopy(seed)
    if isinstance(raw, dict):
        merged.update(copy.deepcopy(raw))
    wanted_spec = _text(merged.get("spec"), spec_for_identity(
        role=role,
        archetype=archetype,
        occupation=occupation,
    ), 24).upper()
    if wanted_spec not in SPEC_WEIGHTS:
        wanted_spec = spec_for_identity(role=role, archetype=archetype, occupation=occupation)
    base_defaults = seed.get("base_stats", {}) if isinstance(seed.get("base_stats"), dict) else {}
    additive_defaults = seed.get("additive_stats", {}) if isinstance(seed.get("additive_stats"), dict) else {}
    result: dict[str, Any] = {
        "schema": SCHEMA,
        "version": VERSION,
        "identity_id": _text(merged.get("identity_id"), identity_id, 64),
        "race": _text(merged.get("race"), "ISLANDER", 24).upper(),
        "class_id": _text(merged.get("class_id"), "npc.traveler", 64),
        "spec": wanted_spec,
        "level": max(1, min(MAX_LEVEL, _safe_int(merged.get("level"), 1))),
        "xp": max(0, min(MAX_XP_GAIN, _safe_int(merged.get("xp"), 0))),
        "xp_to_next": 0,
        "ascension": max(0, min(MAX_ASCENSION, _safe_int(merged.get("ascension"), 0))),
        "paragon": max(0, min(MAX_PARAGON, _safe_int(merged.get("paragon"), 0))),
        "stat_points": max(0, min(MAX_STAT_VALUE, _safe_int(merged.get("stat_points"), 0))),
        "talent_points": max(0, min(MAX_STAT_VALUE, _safe_int(merged.get("talent_points"), 0))),
        "talents": {},
        "base_stats": {},
        "additive_stats": _stat_map(merged.get("additive_stats"), default=additive_defaults),
        "gear_stats": _stat_map(merged.get("gear_stats")),
        "derived_stats": _stat_map(merged.get("derived_stats")),
        "gear_score": round(_clamp(merged.get("gear_score"), 0.0, MAX_STAT_VALUE), 3),
        "power_score": round(_clamp(merged.get("power_score"), 0.0, MAX_STAT_VALUE), 3),
        "equipped_count": max(0, min(MAX_EQUIPPED_SUMMARY, _safe_int(merged.get("equipped_count"), 0))),
        "equipped_items": [],
        "professions": _normalize_professions(merged.get("professions"), seed.get("professions")),
        "last_action_count": max(0, _safe_int(merged.get("last_action_count"), 0)),
        "last_gain": _normalize_event(merged.get("last_gain")),
        "last_power_change": _normalize_event(merged.get("last_power_change")),
        "revision": max(0, _safe_int(merged.get("revision"), 0)),
    }
    result["xp_to_next"] = shared_progression.xp_for_next(result["level"])
    source_talents = merged.get("talents") if isinstance(merged.get("talents"), dict) else {}
    for talent_id in ("trailblazer", "tidewalker", "skybound"):
        result["talents"][talent_id] = max(
            0,
            min(MAX_STAT_VALUE, _safe_int(source_talents.get(talent_id), 0)),
        )
    source_stats = merged.get("base_stats") if isinstance(merged.get("base_stats"), dict) else {}
    for key in STAT_KEYS:
        result["base_stats"][key] = max(
            1,
            min(MAX_STAT_VALUE, _safe_int(source_stats.get(key, base_defaults.get(key, 5)), 5)),
        )
    source_equipped = merged.get("equipped_items")
    if isinstance(source_equipped, list):
        for raw_item in source_equipped[:MAX_EQUIPPED_SUMMARY]:
            if not isinstance(raw_item, dict):
                continue
            result["equipped_items"].append(
                {
                    "instance_id": _text(raw_item.get("instance_id"), limit=64),
                    "definition_id": _text(raw_item.get("definition_id"), limit=96),
                    "slot": _text(raw_item.get("slot"), limit=32).upper(),
                    "score": round(_clamp(raw_item.get("score"), 0.0, MAX_STAT_VALUE), 3),
                    "level": max(1, _safe_int(raw_item.get("level"), 1)),
                    "rarity": _text(raw_item.get("rarity"), "COMMON", 16).upper(),
                    "quality": _text(raw_item.get("quality"), "STANDARD", 16).upper(),
                }
            )
    return result


def _touch(state: dict[str, Any]) -> None:
    state["revision"] = max(0, _safe_int(state.get("revision"), 0)) + 1


def _auto_allocate_stats(state: dict[str, Any]) -> int:
    points = max(0, min(MAX_STAT_VALUE, _safe_int(state.get("stat_points"), 0)))
    stats = state.setdefault("base_stats", {})
    weights = SPEC_WEIGHTS.get(str(state.get("spec")), SPEC_WEIGHTS["EXPLORER"])
    spent = 0
    while points > 0:
        target = max(
            STAT_KEYS,
            key=lambda key: (
                float(weights.get(key, 1)) / max(1.0, _safe_float(stats.get(key), 1.0)),
                weights.get(key, 1),
                -STAT_KEYS.index(key),
            ),
        )
        stats[target] = max(1, min(MAX_STAT_VALUE, _safe_int(stats.get(target), 1) + 1))
        points -= 1
        spent += 1
    state["stat_points"] = points
    return spent


def _auto_allocate_talent(state: dict[str, Any]) -> int:
    points = max(0, min(MAX_STAT_VALUE, _safe_int(state.get("talent_points"), 0)))
    talents = state.setdefault("talents", {})
    target = TALENT_BY_SPEC.get(str(state.get("spec")), "trailblazer")
    rank = max(0, _safe_int(talents.get(target), 0))
    talents[target] = min(MAX_STAT_VALUE, rank + points)
    state["talent_points"] = 0
    return points


def grant_xp(
    state: dict[str, Any],
    amount: Any,
    *,
    source: Any = "",
    item_id: Any = "",
    sim_time: Any = 0.0,
) -> dict[str, Any]:
    """Apply shared player XP rules plus an NPC's deterministic auto-build."""
    gained = max(0, min(MAX_XP_GAIN, _safe_int(amount)))
    state["xp"] = max(0, _safe_int(state.get("xp"), 0)) + gained
    level = max(1, min(MAX_LEVEL, _safe_int(state.get("level"), 1)))
    level_ups = 0
    stat_points_spent = 0
    talent_points_spent = 0
    while level < MAX_LEVEL and state["xp"] >= shared_progression.xp_for_next(level):
        state["xp"] -= shared_progression.xp_for_next(level)
        level += 1
        level_ups += 1
        state["stat_points"] = _safe_int(state.get("stat_points"), 0) + 3
        state["talent_points"] = _safe_int(state.get("talent_points"), 0) + 1
        stat_points_spent += _auto_allocate_stats(state)
        talent_points_spent += _auto_allocate_talent(state)
    state["level"] = level
    state["xp_to_next"] = shared_progression.xp_for_next(level)
    if level == MAX_LEVEL:
        state["paragon"] = min(
            MAX_PARAGON,
            _safe_int(state.get("paragon"), 0) + state["xp"] // 250,
        )
        state["xp"] %= 250
    if gained:
        state["last_gain"] = {
            "kind": "XP",
            "amount": gained,
            "source": _text(source, "WORLD", 48),
            "item_id": _text(item_id, limit=96),
            "time_s": round(max(0.0, _safe_float(sim_time)), 3),
            "level_ups": level_ups,
            "ascension": max(0, min(MAX_ASCENSION, _safe_int(state.get("ascension"), 0))),
        }
        _touch(state)
    return {
        "xp_gained": gained,
        "level_ups": level_ups,
        "level": level,
        "stat_points_spent": stat_points_spent,
        "talent_points_spent": talent_points_spent,
        "ascension": max(0, min(MAX_ASCENSION, _safe_int(state.get("ascension"), 0))),
        "paragon": max(0, _safe_int(state.get("paragon"), 0)),
    }


def ascend(
    state: dict[str, Any],
    *,
    source: Any = "NPC_MILESTONE",
    sim_time: Any = 0.0,
) -> tuple[bool, dict[str, Any]]:
    """Spend real paragon earned at the level cap to begin an ascension."""
    level = max(1, _safe_int(state.get("level"), 1))
    paragon = max(0, _safe_int(state.get("paragon"), 0))
    if level < MAX_LEVEL:
        return False, {
            "error": "NPC_ASCENSION_LEVEL_REQUIRED",
            "required_level": MAX_LEVEL,
        }
    if paragon < ASCENSION_PARAGON_COST:
        return False, {
            "error": "NPC_ASCENSION_PARAGON_REQUIRED",
            "required_paragon": ASCENSION_PARAGON_COST,
            "paragon": paragon,
        }
    current = max(0, min(MAX_ASCENSION, _safe_int(state.get("ascension"), 0)))
    if current >= MAX_ASCENSION:
        return False, {"error": "NPC_ASCENSION_CAP", "cap": MAX_ASCENSION}
    state["paragon"] = paragon - ASCENSION_PARAGON_COST
    state["ascension"] = current + 1
    state["level"] = 1
    state["xp"] = 0
    state["xp_to_next"] = shared_progression.xp_for_next(1)
    base_stats = state.setdefault("base_stats", {})
    for key in STAT_KEYS:
        base_stats[key] = min(
            MAX_STAT_VALUE,
            max(1, _safe_int(base_stats.get(key), 1) + ASCENSION_STAT_BONUS),
        )
    state["last_gain"] = {
        "kind": "ASCENSION",
        "amount": ASCENSION_PARAGON_COST,
        "source": _text(source, "NPC_MILESTONE", 48),
        "item_id": "",
        "time_s": round(max(0.0, _safe_float(sim_time)), 3),
        "level_ups": 0,
        "ascension": state["ascension"],
    }
    _touch(state)
    return True, {
        "ascension": state["ascension"],
        "paragon": state["paragon"],
        "level": state["level"],
        "stat_bonus": ASCENSION_STAT_BONUS,
    }


def grant_profession_xp(
    state: dict[str, Any],
    profession: Any,
    amount: Any,
    *,
    sim_time: Any = 0.0,
) -> dict[str, Any]:
    key = _text(profession, limit=32).upper()
    if key not in PROFESSION_KEYS:
        return {"xp_gained": 0, "error": "NPC_PROFESSION_UNKNOWN", "profession": key}
    gained = max(0, min(MAX_XP_GAIN, _safe_int(amount)))
    professions = state.setdefault("professions", {})
    row = professions.setdefault(key, {"level": 1, "xp": 0, "xp_to_next": 100})
    level = max(1, min(MAX_PROFESSION_LEVEL, _safe_int(row.get("level"), 1)))
    row["xp"] = max(0, _safe_int(row.get("xp"), 0)) + gained
    level_ups = 0
    while level < MAX_PROFESSION_LEVEL and row["xp"] >= 100 + (level - 1) * 50:
        row["xp"] -= 100 + (level - 1) * 50
        level += 1
        level_ups += 1
    row["level"] = level
    row["xp_to_next"] = 100 + (level - 1) * 50
    if gained:
        state["last_gain"] = {
            "kind": "PROFESSION_XP",
            "amount": gained,
            "source": key,
            "item_id": "",
            "time_s": round(max(0.0, _safe_float(sim_time)), 3),
            "level_ups": level_ups,
            "ascension": max(0, min(MAX_ASCENSION, _safe_int(state.get("ascension"), 0))),
        }
        _touch(state)
    return {
        "profession": key,
        "xp_gained": gained,
        "level_ups": level_ups,
        "level": level,
        "xp": row["xp"],
    }


def profession_level(state: dict[str, Any], profession: Any) -> int:
    key = _text(profession, limit=32).upper()
    professions = state.get("professions", {}) if isinstance(state, dict) else {}
    row = professions.get(key) if isinstance(professions, dict) else None
    return max(1, min(MAX_PROFESSION_LEVEL, _safe_int(row.get("level"), 1) if isinstance(row, dict) else 1))


def _item_slot(item: dict[str, Any]) -> str:
    gear = item.get("gear") if isinstance(item.get("gear"), dict) else {}
    return _text(
        item.get("equipped_slot") or gear.get("slot"),
        limit=32,
    ).upper()


def _item_quality(item: dict[str, Any]) -> str:
    gear = item.get("gear") if isinstance(item.get("gear"), dict) else {}
    quality = _text(
        gear.get("quality") or item.get("craft_quality"),
        "STANDARD",
        16,
    ).upper()
    return quality if quality in QUALITY_RANK else "STANDARD"


def _item_stats(item: dict[str, Any]) -> dict[str, float]:
    gear = item.get("gear") if isinstance(item.get("gear"), dict) else {}
    stats = gear.get("stats") if isinstance(gear.get("stats"), dict) else {}
    result: dict[str, float] = {
        _text(key, limit=48).lower(): _safe_float(value)
        for key, value in list(stats.items())[:MAX_DERIVED_STATS]
        if _text(key, limit=48)
    }
    # Deterministic loot affixes live on the instance, outside the gear state.
    # Include them exactly once in NPC power evaluation.
    affixes = item.get("affixes")
    if isinstance(affixes, list):
        for row in affixes[:4]:
            if not isinstance(row, dict):
                continue
            stat = _text(row.get("stat"), limit=48).lower()
            if stat:
                result[stat] = result.get(stat, 0.0) + _safe_float(row.get("value"))
    return result


def item_score(item: Any) -> float:
    """Return a deterministic comparison score for one real gear instance."""
    if not isinstance(item, dict) or not isinstance(item.get("gear"), dict):
        return 0.0
    rarity = _text(item.get("rarity"), "COMMON", 16).upper()
    gear = item.get("gear", {})
    sockets = gear.get("sockets", []) if isinstance(gear.get("sockets"), list) else []
    score = (
        max(1, _safe_int(item.get("level"), 1)) * 10.0
        + RARITY_RANK.get(rarity, 1) * 18.0
        + QUALITY_RANK.get(_item_quality(item), 0) * 8.0
        + min(6, len(sockets)) * 3.0
    )
    for stat, value in _item_stats(item).items():
        if stat == "durability":
            continue
        score += abs(value) * GEAR_STAT_WEIGHTS.get(stat, 0.75)
    return round(max(0.0, min(float(MAX_STAT_VALUE), score)), 3)


def compare_item(candidate: Any, equipped: Any = None) -> dict[str, Any]:
    candidate_score = item_score(candidate)
    equipped_score = item_score(equipped)
    candidate_slot = _item_slot(candidate) if isinstance(candidate, dict) else ""
    equipped_slot = _item_slot(equipped) if isinstance(equipped, dict) else ""
    valid = bool(candidate_score > 0.0 and candidate_slot)
    same_slot = not equipped_slot or candidate_slot == equipped_slot
    upgrade = valid and same_slot and (
        equipped is None or equipped_score <= 0.0 or candidate_score > equipped_score + 0.001
    )
    return {
        "candidate_score": candidate_score,
        "equipped_score": equipped_score,
        "candidate_slot": candidate_slot,
        "upgrade": upgrade,
        "reason": (
            "EMPTY_SLOT" if upgrade and equipped is None else
            "HIGHER_SCORE" if upgrade else
            "NOT_AN_UPGRADE"
        ),
    }


def recalculate(
    state: dict[str, Any],
    equipped_instances: Iterable[dict[str, Any]],
    *,
    source: Any = "",
    sim_time: Any = 0.0,
) -> dict[str, Any]:
    """Derive NPC power only from the supplied canonical EQUIPPED rows."""
    before_gear = round(_clamp(state.get("gear_score"), 0.0, MAX_STAT_VALUE), 3)
    before_power = round(_clamp(state.get("power_score"), 0.0, MAX_STAT_VALUE), 3)
    rows = [
        row for row in list(equipped_instances)[:MAX_EQUIPPED_SUMMARY]
        if isinstance(row, dict)
        and str(row.get("location", "EQUIPPED")).upper() == "EQUIPPED"
        and isinstance(row.get("gear"), dict)
    ]
    rows.sort(key=lambda row: str(row.get("instance_id", "")))
    gear_stats: dict[str, float] = {}
    item_rows: list[dict[str, Any]] = []
    gear_score = 0.0
    for row in rows:
        score = item_score(row)
        gear_score += score
        for stat, value in _item_stats(row).items():
            gear_stats[stat] = gear_stats.get(stat, 0.0) + value
        item_rows.append(
            {
                "instance_id": _text(row.get("instance_id"), limit=64),
                "definition_id": _text(row.get("definition_id"), limit=96),
                "slot": _item_slot(row),
                "score": score,
                "level": max(1, _safe_int(row.get("level"), 1)),
                "rarity": _text(row.get("rarity"), "COMMON", 16).upper(),
                "quality": _item_quality(row),
            }
        )
    gear_stats = {
        key: _number(_clamp(value, -MAX_STAT_VALUE, MAX_STAT_VALUE))
        for key, value in sorted(gear_stats.items())
    }
    base = state.get("base_stats", {}) if isinstance(state.get("base_stats"), dict) else {}
    additive = state.get("additive_stats", {}) if isinstance(state.get("additive_stats"), dict) else {}
    might = _safe_float(base.get("might"), 5.0)
    finesse = _safe_float(base.get("finesse"), 5.0)
    spirit = _safe_float(base.get("spirit"), 5.0)
    grit = _safe_float(base.get("grit"), 5.0)
    gear_value = lambda key: _safe_float(gear_stats.get(key), 0.0)
    derived = {
        "health": 50.0 + grit * 12.0 + gear_value("health") + gear_value("stamina") * 2.0,
        "mana": 30.0 + spirit * 10.0 + gear_value("mana"),
        "damage": might * 2.0 + finesse + gear_value("damage") + gear_value("damage_pct") * 0.1,
        "armor": grit + gear_value("armor"),
        "stamina": grit + gear_value("stamina"),
        "loot_find": _safe_float(additive.get("loot_find")) + gear_value("loot_find"),
        "move_speed": _safe_float(additive.get("move_speed")) + gear_value("move_speed") + gear_value("travel_speed"),
        "swim_speed": _safe_float(additive.get("swim_speed")) + gear_value("swim_speed"),
        "crafting_power": spirit + max(
            [profession_level(state, profession) for profession in PROFESSION_KEYS] or [1]
        ),
    }
    derived = {
        key: _number(_clamp(value, -MAX_STAT_VALUE, MAX_STAT_VALUE))
        for key, value in derived.items()
    }
    talent_total = sum(max(0, _safe_int(value)) for value in state.get("talents", {}).values())
    power_score = (
        max(1, _safe_int(state.get("level"), 1)) * 18.0
        + max(0, _safe_int(state.get("ascension"), 0)) * 150.0
        + max(0, _safe_int(state.get("paragon"), 0)) * 4.0
        + sum(_safe_float(base.get(key), 5.0) for key in STAT_KEYS) * 4.0
        + gear_score
        + talent_total * 7.0
        + _safe_float(derived.get("damage")) * 2.0
        + _safe_float(derived.get("armor"))
    )
    power_score = round(max(0.0, min(float(MAX_STAT_VALUE), power_score)), 3)
    state["gear_stats"] = gear_stats
    state["derived_stats"] = derived
    state["gear_score"] = round(max(0.0, min(float(MAX_STAT_VALUE), gear_score)), 3)
    state["power_score"] = power_score
    state["equipped_count"] = len(item_rows)
    state["equipped_items"] = item_rows
    gear_changed = abs(before_gear - state["gear_score"]) > 0.001
    power_changed = abs(before_power - power_score) > 0.001
    if gear_changed or power_changed:
        state["last_power_change"] = {
            "kind": "GEAR" if gear_changed else "PROGRESSION",
            "amount": int(round(abs(state["gear_score"] - before_gear))) if gear_changed else 0,
            "source": _text(source, "RECALCULATE", 48),
            "item_id": "",
            "time_s": round(max(0.0, _safe_float(sim_time)), 3),
            "level_ups": 0,
            "ascension": max(0, min(MAX_ASCENSION, _safe_int(state.get("ascension"), 0))),
        }
        _touch(state)
    return {
        "changed": gear_changed or power_changed,
        "gear_changed": gear_changed,
        "power_changed": power_changed,
        "previous_gear_score": before_gear,
        "gear_score": state["gear_score"],
        "previous_power_score": before_power,
        "power_score": state["power_score"],
        "equipped_count": len(item_rows),
    }


def apply_world_action(
    state: dict[str, Any],
    action_row: Any,
    *,
    payload: Any = None,
    sim_time: Any = 0.0,
) -> dict[str, Any]:
    """Award XP once for a recorded world action, including blocked outcomes."""
    row = action_row if isinstance(action_row, dict) else {}
    count = max(0, _safe_int(row.get("count"), 0))
    previous_count = max(0, _safe_int(state.get("last_action_count"), 0))
    if count <= previous_count:
        return {"processed": False, "xp_gained": 0, "action_count": count}
    state["last_action_count"] = count
    action = _text(row.get("last_action"), limit=32).upper()
    status = _text(row.get("status"), "NONE", 24).upper()
    if status not in POSITIVE_ACTION_STATUSES:
        _touch(state)
        return {
            "processed": True,
            "xp_gained": 0,
            "action_count": count,
            "action": action,
            "status": status,
        }
    data = payload if isinstance(payload, dict) else {}
    amount = ACTION_XP.get(action, 0)
    if bool(data.get("gear_upgrade")):
        amount += 8
    item_id = _text(data.get("definition_id"), limit=96)
    result = grant_xp(
        state,
        amount,
        source=f"WORLD_{action}",
        item_id=item_id,
        sim_time=sim_time,
    )
    result.update(
        {
            "processed": True,
            "action_count": count,
            "action": action,
            "status": status,
        }
    )
    return result


def summary(state: Any) -> dict[str, Any]:
    return copy.deepcopy(state) if isinstance(state, dict) else starter_state()

