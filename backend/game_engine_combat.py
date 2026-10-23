"""Deterministic combat state for the GAME ENGINE.

Combat is an authoritative simulation layer.  It does not know anything
about QtQuick3D or the DOS renderer: actors have bounded health, cooldown and
engagement state, while the host supplies the progression-derived profile and
commits item/XP/event side effects.
"""

from __future__ import annotations

import copy
import math
from typing import Any
from backend.game_engine_enchants import FAMILIES


SCHEMA = "gg.game-engine.combat.v1"
VERSION = 1
MAX_ACTORS = 128
MAX_HEALTH = 1_000_000.0
MAX_DAMAGE = 100_000.0
MAX_ARMOR = 100_000.0
MAX_COOLDOWN_S = 30.0
PLAYER_RESPAWN_S = 8.0
NPC_RESPAWN_S = 20.0


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return number if math.isfinite(number) else default


def _clamp(value: Any, low: float, high: float, default: float = 0.0) -> float:
    return max(low, min(high, _safe_float(value, default)))


def _text(value: Any, default: str = "", limit: int = 64) -> str:
    return str(value or default).strip()[:limit]



def normalize_effects(raw: Any) -> list[dict[str, Any]]:
    result = []
    for row in raw[:8] if isinstance(raw, list) else []:
        if not isinstance(row, dict) or row.get('kind') not in FAMILIES:
            continue
        kind = row['kind']
        maximum = .8 if kind in ('slow', 'weaken', 'attack_slow', 'lifesteal') else MAX_DAMAGE
        result.append(dict(kind=kind, amount=_clamp(row.get('amount'), 0, maximum),
            duration_s=_clamp(row.get('duration_s'), 0, 15),
            source_id=_text(row.get('source_id'), 'enchant', 96)))
    return result


def normalize_statuses(raw: Any) -> list[dict[str, Any]]:
    result = []
    for row in raw[:12] if isinstance(raw, list) else []:
        if not isinstance(row, dict):
            continue
        effects = normalize_effects([row])
        if not effects or effects[0]['kind'] not in ('burn', 'poison', 'slow', 'snare', 'weaken', 'ward', 'regen', 'attack_slow'):
            continue
        result.append(dict(effects[0], expires_at=max(0, _safe_float(row.get('expires_at'))),
            next_tick_at=max(0, _safe_float(row.get('next_tick_at'))),
            attacker_id=_text(row.get('attacker_id'), limit=64)))
    return result


def status_strength(actor: dict, kind: str, now: float) -> float:
    return max((e['amount'] for e in actor.get('statuses', [])
                if e['kind'] == kind and e['expires_at'] > now), default=0.0)


def movement_scale(actor: dict, now: float) -> float:
    if status_strength(actor, 'snare', now):
        return 0.0
    return 1.0 - status_strength(actor, 'slow', now)


def apply_status(actor: dict, effect: dict, attacker: str, now: float) -> None:
    statuses = actor.setdefault('statuses', [])
    previous = next((e for e in statuses if e['kind'] == effect['kind']
                     and e['source_id'] == effect['source_id'] and e['attacker_id'] == attacker), None)
    row = dict(effect, attacker_id=attacker, expires_at=round(now + effect['duration_s'], 3),
               next_tick_at=round(now + 1, 3))
    # Refreshing poison/burn/regen never postpones a pending tick.
    if previous:
        if previous['expires_at'] >= now:
            row['next_tick_at'] = previous['next_tick_at']
        statuses[statuses.index(previous)] = row
    elif len(statuses) < 12:
        statuses.append(row)


def deal_damage(state: dict, actor: dict, damage: float, attacker: str, now: float) -> tuple[float, float]:
    pending = max(0, damage)
    for ward in actor.get('statuses', []):
        if ward['kind'] == 'ward' and ward['expires_at'] > now:
            blocked = min(pending, ward['amount'])
            pending -= blocked
            ward['amount'] -= blocked
    absorbed = damage - pending
    duel = state.get('duel', {})
    attacker_owner = 'player' if str(attacker).startswith('pet:') else attacker
    if actor.get('id') in duel.get('participants', []) and attacker_owner in duel.get('participants', []) and actor.get('id') != attacker_owner:
        if pending >= max(0., actor['health'] - 1.):
            duel['loser'] = actor['id']
        pending = min(pending, max(0., actor['health'] - 1.))
    dealt = min(actor['health'], pending)
    actor['health'] = round(max(0, actor['health'] - pending), 3)
    actor['last_damage'] = round(dealt, 3)
    actor['last_hit_by'] = attacker
    if actor['health'] <= 0 and actor.get('alive'):
        actor['alive'] = False
        actor['defeated_count'] += 1
        actor['engaged_target'] = ''
        actor['respawn_at'] = round(now + (PLAYER_RESPAWN_S if actor['kind'] == 'PLAYER' else NPC_RESPAWN_S), 3)
        actor['statuses'] = []
        for other in state.get('actors',{}).values():
            if other.get('engaged_target')==actor['id']:other['engaged_target']=''
    return dealt, absorbed


def tick_statuses(state: dict, sim_time: Any) -> list[dict]:
    """Tick once per elapsed second; no damage, XP or healing repeats after death.

    Fixed simulation timestamps make results independent of render FPS. Each
    status lasts at most 15 seconds; catch-up work is bounded by that lifetime.
    """
    now = max(0, _safe_float(sim_time))
    events = []
    changed = False
    for actor in list(state.get('actors', {}).values())[:MAX_ACTORS]:
        if not actor.get('alive'):
            continue
        # Resolve mixed damage/healing in timestamp order, including catch-up.
        # Processing every burn tick before every regen tick changes survival
        # when cadence changes; a single bounded timeline preserves the result.
        for _ in range(12 * 15):
            if not actor.get('alive'):
                break
            due_statuses = [e for e in actor.get('statuses', [])
                if e['kind'] in ('burn', 'poison', 'regen')
                and e['next_tick_at'] <= min(now, e['expires_at']) + .00001]
            if not due_statuses:
                break
            status = min(due_statuses, key=lambda e: (
                e['next_tick_at'], e['kind'], e['source_id'], e['attacker_id']))
            due = status['next_tick_at']
            status['next_tick_at'] = round(due + 1, 3)
            changed = True
            if status['kind'] == 'regen':
                actor['health'] = round(min(actor['max_health'], actor['health'] + status['amount']), 3)
                continue
            dealt, absorbed = deal_damage(state, actor, status['amount'], status['attacker_id'], due)
            event = dict(kind='ENCHANT_TICK', ok=True, status='DEFEATED' if not actor['alive'] else 'HIT',
                attacker_id=status['attacker_id'], defender_id=actor['id'], action_id=status['kind'],
                damage=round(dealt, 3), absorbed=round(absorbed, 3), defeated=not actor['alive'], time_s=due,
                defender_health=actor['health'], defender_max_health=actor['max_health'])
            events.append(event)
        statuses = actor.get('statuses', [])
        remaining = [e for e in statuses if e['expires_at'] > now]
        changed |= len(remaining) != len(statuses)
        actor['statuses'] = remaining
    if events:
        state['last_event'] = copy.deepcopy(events[-1])
    if changed:
        state['revision'] = max(0, _safe_int(state.get('revision'))) + 1
    return events

def profile(
    state: Any,
    *,
    kind: str = "NPC",
    actor_id: str = "",
    role: str = "",
    gear_bonus: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Derive one bounded combat profile from a progression state.

    NPC progression already contains gear-aware derived stats.  The player
    progression uses the same base-stat contract; when the host supplies a
    temporary ``gear_stats`` map, those real equipped item stats are included
    without mutating the progression document.
    """
    source = state if isinstance(state, dict) else {}
    base = source.get("base_stats", {}) if isinstance(source.get("base_stats"), dict) else {}
    derived = source.get("derived_stats", {}) if isinstance(source.get("derived_stats"), dict) else {}
    gear = dict(source.get("gear_stats", {})) if isinstance(source.get("gear_stats"), dict) else {}
    bonus=gear_bonus if isinstance(gear_bonus,dict) else {}
    for key,value in bonus.items():gear[key]=_safe_float(gear.get(key))+_safe_float(value)
    level = max(1, min(60, _safe_int(source.get("level"), 1)))
    ascension = max(0, _safe_int(source.get("ascension"), 0))
    paragon = max(0, _safe_int(source.get("paragon"), 0))
    might = _safe_float(base.get("might"), 5.0)
    finesse = _safe_float(base.get("finesse"), 5.0)
    spirit = _safe_float(base.get("spirit"), 5.0)
    grit = _safe_float(base.get("grit"), 5.0)
    gear_value = lambda key: _safe_float(gear.get(key), 0.0)
    has_derived = any(key in derived for key in ("health", "damage", "armor"))
    max_health = _safe_float(derived.get("health"), 50.0 + grit * 12.0)
    damage = _safe_float(derived.get("damage"), might * 2.0 + finesse)
    armor = _safe_float(derived.get("armor"), grit)
    if not has_derived:
        max_health += gear_value("health") + gear_value("stamina") * 2.0
        damage += gear_value("damage") + gear_value("spell_power") * 0.35
        armor += gear_value("armor")
    else:
        max_health += _safe_float(bonus.get('health'))+_safe_float(bonus.get('stamina'))*2.
        damage += _safe_float(bonus.get('damage'))+_safe_float(bonus.get('spell_power'))*.35
        armor += _safe_float(bonus.get('armor'))
    crit = 0.04 + finesse * 0.004 + gear_value("crit") * 0.01
    crit += ascension * 0.006 + paragon * 0.0005
    attack_speed = 0.95 - min(0.35, finesse * 0.012)
    attack_speed -= min(0.18, gear_value("attack_speed") * 0.01)
    return {
        "id": _text(actor_id, "actor", 64),
        "kind": _text(kind, "NPC", 16).upper(),
        "role": _text(role, "", 32).upper(),
        "level": level,
        "ascension": ascension,
        "power_score": round(max(0.0, _safe_float(source.get("power_score"))), 3),
        "max_health": round(_clamp(max_health, 1.0, MAX_HEALTH, 100.0), 3),
        "damage": round(_clamp(damage, 1.0, MAX_DAMAGE, 10.0), 3),
        "armor": round(_clamp(armor, 0.0, MAX_ARMOR), 3),
        "crit_chance": round(_clamp(crit, 0.0, 0.75), 4),
        "attack_cooldown_s": round(_clamp(attack_speed, 0.2, MAX_COOLDOWN_S, 0.95), 3),
        "enchant_effects": normalize_effects(source.get("enchant_effects", [])),
        "attack_range_m": round(
            _clamp(2.4 + finesse * 0.025 + gear_value("attack_range"), 1.25, 8.0, 2.5),
            3,
        ),
    }


def new_state() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "actors": {},
        "last_event": {},
        "revision": 0,
    }


def _normalize_actor(raw: Any, actor_id: str) -> dict[str, Any]:
    row = raw if isinstance(raw, dict) else {}
    maximum = _clamp(row.get("max_health"), 1.0, MAX_HEALTH, 100.0)
    health = _clamp(row.get("health"), 0.0, maximum, maximum)
    return {
        "id": _text(row.get("id"), actor_id, 64),
        "kind": _text(row.get("kind"), "NPC", 16).upper(),
        "alive": bool(row.get("alive", health > 0.0)),
        "health": round(health, 3),
        "max_health": round(maximum, 3),
        "cooldown_until": round(max(0.0, _safe_float(row.get("cooldown_until"))), 3),
        "weapon_cooldowns": {str(key)[:96]:max(0,_safe_float(value)) for key,value in list(row.get('weapon_cooldowns',{}).items())[:32]} if isinstance(row.get('weapon_cooldowns'),dict) else {},
        "engaged_target": _text(row.get("engaged_target"), limit=64),
        "respawn_at": round(max(0.0, _safe_float(row.get("respawn_at"))), 3),
        "defeated_count": max(0, min(1_000_000, _safe_int(row.get("defeated_count")))),
        "last_damage": round(_clamp(row.get("last_damage"), 0.0, MAX_DAMAGE), 3),
        "last_hit_by": _text(row.get("last_hit_by"), limit=64),
        "statuses": normalize_statuses(row.get("statuses", [])),
    }


def normalize_state(raw: Any) -> dict[str, Any]:
    base = new_state()
    source = raw if isinstance(raw, dict) else {}
    actors = source.get("actors", {})
    if isinstance(actors, dict):
        for actor_id, value in list(actors.items())[:MAX_ACTORS]:
            wanted = _text(actor_id, limit=64)
            if wanted:
                base["actors"][wanted] = _normalize_actor(value, wanted)
    last_event = source.get("last_event")
    if isinstance(last_event, dict):
        base["last_event"] = {
            key: copy.deepcopy(last_event[key])
            for key in (
                "kind",
                "attacker_id",
                "defender_id",
                "action_id",
                "damage",
                "critical",
                "defeated",
                "time_s",
                "enchant_effects",
                "absorbed",
            )
            if key in last_event
        }
    base["revision"] = max(0, _safe_int(source.get("revision")))
    return base


def ensure_actor(
    state: dict[str, Any],
    actor_id: Any,
    profile_row: dict[str, Any],
) -> dict[str, Any]:
    actors = state.setdefault("actors", {})
    wanted = _text(actor_id, "actor", 64)
    profile_max = _clamp(profile_row.get("max_health"), 1.0, MAX_HEALTH, 100.0)
    current = actors.get(wanted)
    if not isinstance(current, dict):
        current = _normalize_actor(
            {
                "id": wanted,
                "kind": profile_row.get("kind", "NPC"),
                "max_health": profile_max,
                "health": profile_max,
                "alive": True,
            },
            wanted,
        )
        actors[wanted] = current
        return current
    old_max = _clamp(current.get("max_health"), 1.0, MAX_HEALTH, profile_max)
    old_health = _clamp(current.get("health"), 0.0, old_max, old_max)
    if bool(current.get("alive", True)):
        ratio = old_health / old_max if old_max > 0.0 else 1.0
        current["health"] = round(_clamp(profile_max * ratio, 0.0, profile_max), 3)
    current["max_health"] = round(profile_max, 3)
    current["kind"] = _text(profile_row.get("kind"), current.get("kind", "NPC"), 16).upper()
    current["id"] = wanted
    return current


def respawn_actor(
    state: dict[str, Any],
    actor_id: Any,
    profile_row: dict[str, Any],
    sim_time: Any,
) -> dict[str, Any] | None:
    actor = ensure_actor(state, actor_id, profile_row)
    now = max(0.0, _safe_float(sim_time))
    if actor.get("alive") or now < _safe_float(actor.get("respawn_at")):
        return None
    actor["alive"] = True
    actor["health"] = actor["max_health"]
    actor["respawn_at"] = 0.0
    actor["cooldown_until"] = 0.0
    actor["engaged_target"] = ""
    actor["last_damage"] = 0.0
    actor["statuses"] = []
    state["revision"] = max(0, _safe_int(state.get("revision"))) + 1
    return copy.deepcopy(actor)


def resolve_attack(
    state: dict[str, Any],
    *,
    attacker_id: Any,
    defender_id: Any,
    attacker_profile: dict[str, Any],
    defender_profile: dict[str, Any],
    sim_time: Any,
    seed: Any = 1,
    action_id: Any = "basic_attack",
    cooldown_group: str = "",
) -> dict[str, Any]:
    """Resolve one deterministic attack and mutate only combat state."""
    attacker_key = _text(attacker_id, limit=64)
    defender_key = _text(defender_id, limit=64)
    now = max(0.0, _safe_float(sim_time))
    attacker = ensure_actor(state, attacker_key, attacker_profile)
    defender = ensure_actor(state, defender_key, defender_profile)
    common = {
        "schema": SCHEMA,
        "version": VERSION,
        "attacker_id": attacker_key,
        "defender_id": defender_key,
        "action_id": _text(action_id, "basic_attack", 48),
        "time_s": round(now, 3),
    }
    if not attacker.get("alive"):
        return {**common, "ok": False, "status": "ATTACKER_DEFEATED", "damage": 0.0}
    if not defender.get("alive"):
        return {**common, "ok": False, "status": "TARGET_DEFEATED", "damage": 0.0}
    duel = state.get('duel', {})
    attacker_owner = 'player' if attacker_key.startswith('pet:') else attacker_key
    if attacker_owner in duel.get('participants', []) and defender_key in duel.get('participants', []) and (duel.get('phase') != 'ACTIVE' or duel.get('loser')):
        return {**common, 'ok': False, 'status': 'DUEL_COUNTDOWN' if not duel.get('loser') else 'DUEL_FINISHED', 'damage': 0.0}
    weapon_cooldowns=attacker.setdefault('weapon_cooldowns',{})
    cooldown_until = _safe_float(weapon_cooldowns.get(cooldown_group,0) if cooldown_group else attacker.get("cooldown_until"))
    if now + 0.0001 < cooldown_until:
        return {
            **common,
            "ok": False,
            "status": "COOLDOWN",
            "damage": 0.0,
            "cooldown_remaining_s": round(cooldown_until - now, 3),
        }
    raw_seed = _safe_int(seed, 1) & 0xFFFFFFFF
    roll = ((raw_seed * 1664525 + 1013904223) & 0xFFFFFFFF) / 4294967296.0
    critical = roll < _clamp(attacker_profile.get("crit_chance"), 0.0, 0.75)
    base_damage = _clamp(attacker_profile.get("damage"), 1.0, MAX_DAMAGE, 1.0)
    armor = _clamp(defender_profile.get("armor"), 0.0, MAX_ARMOR)
    base_damage *= 1.0 - status_strength(attacker, "weaken", now)
    damage = max(1.0, base_damage * (1.5 if critical else 1.0) - armor * 0.35)
    damage = round(_clamp(damage, 1.0, MAX_DAMAGE, 1.0), 3)
    effects = normalize_effects(attacker_profile.get("enchant_effects", []))
    damage += sum(e['amount'] for e in effects if e['kind'] in ('fire', 'shock', 'acid', 'arcane', 'frost'))
    damage = min(MAX_DAMAGE, damage)
    dealt, absorbed = deal_damage(state, defender, damage, attacker_key, now)
    applied = []
    for effect in effects:
        kind, amount = effect['kind'], effect['amount']
        if kind in ('fire', 'shock', 'acid', 'arcane', 'frost'):
            applied.append(dict(effect))
            continue
        if kind in ('heal', 'lifesteal'):
            amount = amount if kind == 'heal' else dealt * amount
            restored = min(amount, attacker['max_health'] - attacker['health'])
            attacker['health'] = round(attacker['health'] + restored, 3)
            applied.append(dict(effect, restored_health=round(restored, 3)))
            continue
        recipient = attacker if kind in ('ward', 'regen') else defender
        if recipient.get('alive'):
            apply_status(recipient, effect, attacker_key, now)
            applied.append(dict(effect))
    next_attack = now + min(MAX_COOLDOWN_S,
            _clamp(attacker_profile.get("attack_cooldown_s"), 0.04 if cooldown_group else 0.2, MAX_COOLDOWN_S, 0.95)
            * (1.0 + status_strength(attacker, 'attack_slow', now)))
    if not cooldown_group:
        next_attack = round(next_attack, 3)
    if cooldown_group:
        for key in list(weapon_cooldowns):
            if weapon_cooldowns[key]<=now:del weapon_cooldowns[key]
        weapon_cooldowns[str(cooldown_group)[:96]]=next_attack
    else:attacker['cooldown_until']=next_attack
    damage = round(dealt, 3)
    defeated = not defender['alive']
    if not defeated:
        defender['engaged_target'] = attacker_key
    attacker["engaged_target"] = defender_key if not defeated else ""
    result = {
        **common,
        "ok": True,
        "status": "DEFEATED" if defeated else "HIT",
        "damage": damage,
        "critical": bool(critical),
        "absorbed": round(absorbed, 3),
        "enchant_effects": applied,
        "defeated": bool(defeated),
        "defender_health": defender["health"],
        "defender_max_health": defender["max_health"],
        "cooldown_s": round(next_attack - now, 3),
    }
    state["last_event"] = copy.deepcopy(result)
    state["revision"] = max(0, _safe_int(state.get("revision"))) + 1
    return result


def view(state: Any) -> dict[str, Any]:
    source = normalize_state(state)
    actors = source.get("actors", {})
    rows: list[dict[str, Any]] = []
    if isinstance(actors, dict):
        for actor_id in sorted(actors)[:MAX_ACTORS]:
            row = actors.get(actor_id)
            if isinstance(row, dict):
                rows.append(copy.deepcopy(row))
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "actors": rows,
        "active": sum(1 for row in rows if row.get("alive")),
        "defeated": sum(1 for row in rows if not row.get("alive")),
        "last_event": copy.deepcopy(source.get("last_event", {})),
        "revision": max(0, _safe_int(source.get("revision"))),
        "policy": "FIXED_STEP_DETERMINISTIC_DAMAGE_WITH_REAL_ACTOR_STATE",
    }
