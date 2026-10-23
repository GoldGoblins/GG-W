"""36 authored pistol constructions; names describe visual inspirations.

Mechanisms and material themes describe the authored meshes. Matching firing,
ammunition and reload rules live in game_engine_firearms. Both use the same identity.
"""
import json
from functools import lru_cache
from pathlib import Path

# name, construction, barrel length, bore housing radius, grip, palette
PISTOLS=(
 ('Sea salt flintlock','flintlock',.58,.051,'hook','wood'),
 ('Colt 1911 midnight','1911',.49,.033,'angled','iron'),
 ('Four wing duckfoot','duckfoot',.44,.038,'hook','bronze'),
 ('Night courier suppressed pistol','silenced',.71,.032,'angled','iron'),
 ('Pearl wheellock','wheellock',.48,.053,'round','cream'),
 ('Pocket derringer','derringer',.25,.033,'round','pink'),
 ('Pirate trumpet blunderbuss','blunderbuss',.73,.069,'sweep','bronze'),
 ('Vented frontier revolver','target',.80,.047,'angled','iron'),
 ('Bulldog snubnose revolver','snubnose',.26,.065,'round','iron'),
 ('Compact Uzi','uzi',.41,.036,'straight','iron'),
 ('Twin barrel hunting shotgun','hunting',1.06,.048,'sweep','wood'),
 ('Pump action trench shotgun','pump',1.10,.052,'straight','iron'),
 ('Colt 1911 ivory longslide','1911_long',.63,.032,'angled','cream'),
 ('Frontier lever action rifle','lever_rifle',1.12,.039,'sweep','bronze'),
 ('Engraved over under shotgun','breakshot',.98,.045,'round','cream'),
 ('Long watch scoped bolt rifle','bolt',1.40,.034,'straight','iron'),
 ('Curved magazine assault rifle','assault',.96,.037,'angled','wood'),
 ('Bullpup pulse carbine','bullpup',.78,.044,'straight','green'),
 ('Compact box SMG','smg',.35,.036,'straight','red'),
 ('Broomhandle laser pistol','boxmag',.63,.042,'round','wood'),
 ('Circular disc thrower','disc',.79,.065,'straight','orange'),
 ('Six barrel clockwork gatling','gatling',.91,.041,'straight','bronze'),
 ('Open rail lightning rifle','rail',1.18,.056,'angled','turquoise'),
 ('Skullcap rocket launcher','rocket',1.06,.146,'straight','red'),
 ('Bulldog block blaster','blaster',.53,.111,'straight','blue'),
 ('Voltaic plasma cannon','plasma',.78,.136,'angled','purple'),
 ('Prism needle caster','prism',.72,.043,'angled','ice'),
 ('Gargoyle wing pistol','demon',.67,.051,'claw','purple'),
 ('Honeycomb swarm scatterer','hive',.55,.043,'round','gold'),
 ('Thorn seed launcher','thorn',.61,.065,'vine','green'),
 ('Conch tide pistol','conch',.55,.092,'sweep','turquoise'),
 ('Dragon maw pistol','dragon',.61,.076,'claw','red'),
 ('Raven feather caster','raven',.76,.040,'claw','purple'),
 ('Twin frost fork','frost',.63,.042,'angled','ice'),
 ('Squid ink pistol','squid',.49,.078,'tentacle','turquoise'),
 ('Phoenix flare pistol','phoenix',.75,.053,'sweep','orange'),
)

TWO_HANDED=frozenset(('hunting','pump','lever_rifle','breakshot','bolt','assault','bullpup','disc','gatling','rail','rocket','plasma','hive'))
SUBTYPES={'hunting':'shotgun','pump':'shotgun','breakshot':'shotgun','lever_rifle':'rifle','bolt':'rifle','assault':'rifle','bullpup':'rifle','uzi':'smg','smg':'smg','gatling':'gatling','rail':'railgun','rocket':'launcher','plasma':'cannon','disc':'launcher','hive':'cannon'}


def pistol_name(variant):return PISTOLS[int(variant)%36][0]

def pistol_visual(variant):return _visuals().get(int(variant)%36,{})

@lru_cache(maxsize=1)
def _visuals():
    path=Path(__file__).resolve().parents[1]/'qml/assets/authored/items/weapon-pistol.variants.json'
    if not path.is_file():return {}
    return {r['variant']:r for r in json.loads(path.read_text())}
