"""36 independent, stylised sword constructions, authored offline.

Names describe visual references, not historically exact reproductions.
Blade dimensions are metres before the item's uniform game scale.
"""
SWORDS = (
    # name, blade length, grip length, half width, curvature, guard, profile
    ('Swept-hilt rapier',1.48,.30,.035,.00,'swept','needle'),
    ('Cup-hilt rapier',1.25,.26,.027,.00,'cup','needle'),
    ('Estoc',1.55,.40,.052,.00,'straight','estoc'),
    ('Smallsword',.96,.24,.027,.00,'shell','needle'),
    ('Cavalry sabre',1.13,.29,.085,.30,'knuckle','single'),
    ('Shamshir',1.28,.25,.074,.59,'short','single'),
    ('Basket cutlass',.83,.32,.16,.23,'basket','belly'),
    ('Broad scimitar',1.13,.28,.22,.61,'horns','scimitar'),
    ('Katana',1.26,.48,.073,.17,'tsuba','single'),
    ('Wakizashi',.72,.32,.092,.12,'square_tsuba','single'),
    ('Nodachi',1.95,.66,.095,.25,'tsuba','single'),
    ('Tachi',1.35,.43,.069,.30,'flower_tsuba','single'),
    ('Basket broadsword',1.12,.34,.14,.00,'basket','double'),
    ('Arming sword',1.02,.26,.12,.00,'straight','double'),
    ('Ulfberht-inspired sword',.98,.30,.15,.00,'viking','fuller'),
    ('Migration sword',.92,.28,.16,.00,'lobed','fuller'),
    ('Longsword',1.46,.52,.125,.00,'downturned','double'),
    ('Zweihander',1.92,.72,.145,.00,'lugs','ricasso'),
    ('Claymore',1.62,.60,.14,.00,'quatrefoil','double'),
    ('Falchion',.94,.29,.23,.13,'downturned','falchion'),
    ('Messer',1.05,.35,.145,.06,'nagel','single'),
    ('Khopesh',1.08,.29,.13,.62,'egyptian','sickle'),
    ('Gladius',.68,.25,.17,.00,'barrel','waist'),
    ('Xiphos',.67,.25,.20,.00,'short','leaf'),
    ('Highland dirk',.51,.27,.075,.00,'none','double'),
    ('Rondel dagger',.50,.22,.043,.00,'rondel','estoc'),
    ('Parrying dagger',.48,.23,.092,.00,'swept_dagger','double'),
    ('Stiletto',.49,.22,.023,.00,'short','needle'),
    ('Five-wave kris',.67,.25,.11,.00,'kris','wave5'),
    ('Nine-wave kris',.91,.30,.095,.00,'kris','wave9'),
    ('Flamberge',1.68,.61,.11,.00,'lugs','wave7'),
    ('Kukri',.54,.25,.19,.23,'kukri','kukri'),
    ('Tanto',.40,.25,.09,.035,'small_tsuba','tanto'),
    ('Jian',1.08,.32,.10,.00,'cloud','double'),
    ('Dao',.93,.31,.16,.28,'disc','dao'),
    ('Moon cleaver',1.18,.42,.30,.31,'crescent','fantasy'),
)

def sword_name(variant):
    return SWORDS[int(variant)%len(SWORDS)][0]

def sword_wielding(variant):
    return '2H' if int(variant)%len(SWORDS) in (10,16,17,18,30) else '1H'

def sword_grip_offset(variant):
    # Authored origin is the pommel. Place the palm toward the guard.
    return [0.,-SWORDS[int(variant)%len(SWORDS)][2]*.7,0.]

def sword_effect(variant):
    """Small compiled visual metadata; never read a GLB on the simulation tick."""
    return _visuals().get(int(variant)%len(SWORDS),{})

from functools import lru_cache

@lru_cache(maxsize=1)
def _visuals():
    import json
    from pathlib import Path
    path=Path(__file__).resolve().parents[1]/'qml/assets/authored/items/weapon-sword.variants.json'
    if not path.is_file():return {}
    rows=json.loads(path.read_text())
    return {r['variant']:r.get('weapon_fx',{}).get('authored',{}) for r in rows}
