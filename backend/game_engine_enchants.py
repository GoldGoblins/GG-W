"""Authored weapon colors and authoritative on-hit rules, shared with the FX UI.

Effects are resolved from equipped item IDs, never from a client-supplied stat.
Amounts are flat starter values; durations and stacking are bounded by combat.
"""
from __future__ import annotations
import copy


def effect(kind: str, amount: float, duration: float = 0) -> dict:
    return dict(kind=kind, amount=amount, duration_s=duration)


# ID, display name, exact cloud colors, actual successful-hit behavior, UI text.
_ROWS = (
    ('VIOLET', 'Void Whisper', '#9956ef', '#b87aff', [effect('weaken', .18, 4)], 'Purple: target deals 18% less damage for 4s.'),
    ('MAGENTA', 'Blood Orchid', '#ed36cc', '#ff6fe2', [effect('lifesteal', .16)], 'Magenta: steal 16% of damage dealt as health.'),
    ('PINK', 'Roseheart', '#ff85bb', '#ffc2d8', [effect('heal', 3)], 'Pink: restore 3 health on a successful hit.'),
    ('RED', 'Crimson Ember', '#f43c4b', '#ff666b', [effect('burn', 2, 4)], 'Red: burn for 2 damage each second for 4s.'),
    ('YELLOW', 'Thunder Gold', '#f4dd36', '#fff081', [effect('shock', 4)], 'Yellow: +4 lightning damage on hit.'),
    ('WHITE', 'Moonward', '#ddeaf5', '#fffefa', [effect('ward', 5, 4)], 'White: gain a 5-damage shield for 4s (refreshes).'),
    ('GREEN', 'Viper Moss', '#32b86a', '#6bd992', [effect('poison', 1.5, 6)], 'Green: poison for 1.5 damage each second for 6s.'),
    ('LIME', 'Caustic Thorn', '#9be32c', '#c9f766', [effect('acid', 4)], 'Lime: +4 acid damage on hit.'),
    ('TURQUOISE', 'Tidepulse', '#35cfc3', '#79ece2', [effect('regen', 1.5, 4)], 'Turquoise: regenerate 1.5 health each second for 4s.'),
    ('BLUE', 'Glacier Edge', '#428aef', '#79b7ff', [effect('slow', .3, 4)], 'Blue: enemy movement slowed by 30% for 4s.'),
    ('ORANGE', 'Forgeflame', '#f38624', '#ffc36a', [effect('fire', 4)], 'Orange: +4 fire damage on hit.'),
    ('INDIGO', 'Duskbind', '#565bdf', '#8b91fa', [effect('snare', 1, 1.2)], 'Indigo: root enemy movement for 1.2s; attacks remain possible.'),
    ('MAGENTA_RED', 'Bloodfire', '#ed36cc', '#f43c4b', [effect('lifesteal', .1), effect('burn', 1, 4)], 'Magenta / red: 10% lifesteal and 1 burn damage per second for 4s.'),
    ('YELLOW_ORANGE', 'Solar Tempest', '#f4dd36', '#f38624', [effect('burn', 1, 3), effect('ward', 3, 3)], 'Yellow / orange: 1 fire damage per second for 3s; gain a golden 3-damage shield for 3s.'),
    ('BLUE_TURQUOISE', 'Frozen Tide', '#428aef', '#35cfc3', [effect('slow', .2, 4), effect('regen', 1, 4)], 'Blue / turquoise: enemy movement -20%; regenerate 1 health per second for 4s.'),
    ('GREEN_YELLOW', 'Stormvenom', '#32b86a', '#f4dd36', [effect('poison', 1, 4), effect('attack_slow', .15, 3)], 'Green / yellow: 1 poison damage per second for 4s; enemy attack interval +15% for 3s.'),
    ('PINK_VIOLET', 'Dreamrose', '#ff85bb', '#9956ef', [effect('heal', 2), effect('weaken', .1, 3)], 'Pink / purple: restore 2 health; enemy damage -10% for 3s.'),
    ('TURQUOISE_LIME', 'Reef Venom', '#35cfc3', '#9be32c', [effect('regen', 1, 3), effect('acid', 2)], 'Turquoise / lime: +2 acid damage; regenerate 1 health per second for 3s.'),
)
CATALOG = {
    'enchant.chromatic.' + style.lower(): dict(
        id='enchant.chromatic.' + style.lower(), name=name, stat='damage', value=0,
        allowed_categories=['WEAPON'], tags=['ENCHANT', 'COMBAT', style],
        visual_fx=style, colors=[a, b], on_hit=rules, description=description,
    ) for style, name, a, b, rules, description in _ROWS
}
# Existing saved enchants keep their IDs and stats, and gain real elemental hits.
LEGACY_EFFECTS = {
    'enchant.ember_edge': [effect('burn', 1, 3)],
    'enchant.venom_edge': [effect('poison', 1, 4)],
    'enchant.storm_edge': [effect('shock', 2)],
    'enchant.arcane_edge': [effect('arcane', 2)],
    'enchant.shadow_edge': [effect('lifesteal', .1)],
    'enchant.sun_lance': [effect('fire', 2)],
    'enchant.smoke_edge': [effect('weaken', .1, 3)],
}



FAMILIES = {
    **dict.fromkeys(('burn', 'poison', 'fire', 'shock', 'acid', 'arcane', 'frost'), 'OFFENSIVE'),
    **dict.fromkeys(('slow', 'snare', 'weaken', 'ward', 'attack_slow'), 'DEFENSIVE'),
    **dict.fromkeys(('heal', 'regen', 'lifesteal'), 'RECOVERY'),
}
for row in CATALOG.values():
    row['tier'] = len(row['on_hit'])
    row['families'] = sorted({FAMILIES[e['kind']] for e in row['on_hit']})
    row['required_level'] = 1
for style, name, colors, rules in (
    ('TRIAD_FLAME', 'Phoenix Covenant', ['#f43c4b', '#ddeaf5', '#ff85bb'],
     [effect('burn', 3, 4), effect('ward', 6, 4), effect('heal', 3)]),
    ('TRIAD_FROST', 'Glacial Trinity', ['#9956ef', '#428aef', '#35cfc3'],
     [effect('arcane', 5), effect('slow', .35, 4), effect('regen', 2, 4)]),
    ('TRIAD_VENOM', 'Ancient Thorn', ['#32b86a', '#565bdf', '#ed36cc'],
     [effect('poison', 3, 4), effect('snare', 1, 1.2), effect('lifesteal', .2)]),
):
    key = 'enchant.chromatic.' + style.lower()
    CATALOG[key] = dict(id=key, name=name, stat='damage', value=0,
        allowed_categories=['WEAPON'], tags=['ENCHANT', 'ARTIFACT'],
        visual_fx=style, colors=colors, on_hit=rules, tier=3,
        families=['OFFENSIVE', 'DEFENSIVE', 'RECOVERY'], required_level=60,
        description='Artifact / level 60: ' + '; '.join(
            e['kind'] + ' ' + str(e['amount']) + (' / ' + str(e['duration_s']) + 's' if e['duration_s'] else '')
            for e in rules))
GEAR_CATALOG = {}
for slug, name, stat, value in (
    ('vitality', 'Vitality Stitch', 'health', 12),
    ('armor', 'Stoneweave', 'armor', 4),
    ('stamina', 'Enduring Thread', 'stamina', 5),
    ('precision', 'Keen Stitch', 'crit', 2),
    ('celerity', 'Swiftweave', 'attack_speed', 2),
    ('spellpower', 'Spellweave', 'spell_power', 6),
):
    key = 'enchant.gear.' + slug
    GEAR_CATALOG[key] = dict(id=key, name=name, stat=stat, value=value,
        allowed_categories=['ARMOR', 'TRINKET', 'UTILITY', 'SHIELD'],
        tags=['ENCHANT', 'STAT_BOOST'], visual_fx='', required_level=1,
        tier=1, description=name + ': +' + str(value) + ' ' + stat.replace('_', ' '))


def definition(key: str) -> dict:
    """Custom scrolls encode a validated selection of authored single effects."""
    if key in CATALOG or key in GEAR_CATALOG:
        return copy.deepcopy(CATALOG.get(key, GEAR_CATALOG.get(key)))
    if not key.startswith('enchant.custom.') or len(key) > 96:
        return {}
    parts = key.removeprefix('enchant.custom.').split('+')
    if not 1 <= len(parts) <= 3 or len(set(parts)) != len(parts):
        return {}
    parts.sort()
    key = 'enchant.custom.' + '+'.join(parts)
    rows = [CATALOG.get('enchant.chromatic.' + part) for part in parts]
    if any(not row or row['tier'] != 1 for row in rows):
        return {}
    rules = [copy.deepcopy(row['on_hit'][0]) for row in rows]
    families = sorted({FAMILIES[e['kind']] for e in rules})
    if len(parts) == 3 and len(families) != 3:
        return {}
    return dict(id=key, name=' + '.join(row['name'] for row in rows),
        stat='damage', value=0, allowed_categories=['WEAPON'],
        tags=['ENCHANT', 'CUSTOM_SCROLL'], visual_fx='CUSTOM',
        colors=[row['colors'][0] for row in rows], on_hit=rules,
        tier=len(parts), families=families, required_level=60 if len(parts) == 3 else 1,
        description=' '.join(row['description'] for row in rows))


def scroll_cost(row: dict) -> dict:
    tier = row.get('tier', 1)
    return {'material.fiber': tier, 'material.runic_oil': tier,
            'item.moon_shard': 2 if tier == 3 else 1}


def equipped_effects(items: list[dict], level: int = 60) -> list[dict]:
    """Resolve at most two enchants per equipped weapon from trusted definitions."""
    result = []
    for item in items:
        gear = item.get('gear', {})
        if not isinstance(gear, dict) or gear.get('base_type') not in ('SWORD', 'AXE', 'MACE', 'BOW', 'STAFF', 'DAGGER', 'PISTOL'):
            continue
        for enchant in gear.get('enchantments', [])[:2]:
            if not isinstance(enchant, dict):
                continue
            key = str(enchant.get('id', ''))
            row = definition(key)
            if row and level < row['required_level']:
                continue
            rules = row.get('on_hit', LEGACY_EFFECTS.get(key, []))
            for rule in rules:
                result.append(dict(copy.deepcopy(rule), source_id=row.get("id", key)))
    return result[:8]


def visual_catalog() -> list[dict]:
    return [dict(id=row['id'], name=row['name'], style=row['visual_fx'],
                 colors=row['colors'], description=row['description'], tier=row['tier'],
                 families=row['families'], required_level=row['required_level'])
            for row in CATALOG.values()]


def firearm_bursts(item: dict, level: int = 60) -> list[dict]:
    """Trusted colours and styles captured with a shot, including legacy saves."""
    legacy={
        'enchant.ember_edge':('FIRE',['#ff9e39','#ffe37a']),
        'enchant.venom_edge':('GAS',['#81d8a2','#b9ed72']),
        'enchant.storm_edge':('LIGHTNING',['#77cfff','#d5f4ff']),
        'enchant.arcane_edge':('ARCANE',['#bf71ff','#edb9ff']),
        'enchant.shadow_edge':('SHADOW',['#9956ef','#ed36cc']),
        'enchant.sun_lance':('LASER',['#ff6176','#ffe3c0']),
        'enchant.smoke_edge':('SMOKE',['#a7aaa9','#e0d9cc']),
    }
    out=[]
    for enchant in item.get('gear',{}).get('enchantments',[])[:2]:
        key=str(enchant.get('id',''));row=definition(key)
        if row:
            if level<row['required_level']:continue
            style,colors=row['visual_fx'],row['colors'];rules=row['on_hit']
        elif key in legacy:
            style,colors=legacy[key];rules=LEGACY_EFFECTS[key]
        else:continue
        out.append(dict(id=key,style=style,colors=list(colors),kinds=[r['kind'] for r in rules]))
    return out
