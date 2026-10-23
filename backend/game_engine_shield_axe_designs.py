"""Curated constructions, independent of camera, streaming and world placement.

These are visual equipment designs. Historical names are shape references;
they do not introduce new combat classes or historical reproduction claims.
"""
from functools import lru_cache
from pathlib import Path
import json

# name, outline, width, height, construction, ornament, palette
SHIELDS = (
    ('Bronze buckler','round',.52,.52,'metal','boss','bronze'),
    ('Swordcatcher','catcher',.62,.62,'metal','spokes','iron'),
    ('Wicker target','round',.88,.94,'woven','weave','reed'),
    ('Split plank round','round',1.10,1.12,'wood','planks','wood'),
    ('Highland targe','round',.90,.90,'hide','knots','red'),
    ('Norman kite','kite',.86,1.65,'wood','cross','blue'),
    ('Lion heater','heater',1.04,1.12,'metal','lion','red'),
    ('Crossbow pavise','pavise',.90,1.72,'wood','spine','blue'),
    ('Curved scutum','scutum',1.00,1.58,'hide','wings','red'),
    ('Sunken hoplon','round',1.17,1.17,'metal','wave','bronze'),
    ('Crescent pelta','pelta',1.28,.88,'hide','crescent','reed'),
    ('Long hide shield','oval',.66,1.76,'hide','hidebars','cream'),
    ('Timber tate','rect',.92,1.58,'wood','crossbars','wood'),
    ('Octagonal target','octagon',1.04,1.04,'metal','diamonds','blue'),
    ('Dragon wing','wing',1.12,1.45,'hide','wingribs','purple'),
    ('Giant scallop','scallop',1.26,1.15,'shell','shellribs','pink'),
    ('Turtle carapace','oval',1.01,1.25,'shell','hexes','green'),
    ('Curled leaf','leaf',.94,1.40,'leaf','veins','green'),
    ('Butterfly guard','butterfly',1.35,1.03,'hide','wingdots','turquoise'),
    ('Obsidian shard','shard',.93,1.34,'stone','fractures','purple'),
    ('Crystal bastion','crystal',.97,1.35,'crystal','prisms','ice'),
    ('Bone rib cage','ribs',1.02,1.34,'bone','ribs','cream'),
    ('Horned tribal mask','mask',1.09,1.33,'wood','mask','red'),
    ('Solar aegis','sun',1.18,1.18,'metal','sun','gold'),
    ('Moon crescent','moon',1.15,1.28,'metal','moon','purple'),
    ('Star sentinel','star',1.25,1.25,'metal','star','blue'),
    ('Clockwork cog','gear',1.23,1.23,'metal','gear','bronze'),
    ('Harbour anchor','anchor',1.20,1.34,'metal','anchor','iron'),
    ('Open grimoire','book',1.20,1.09,'hide','book','purple'),
    ('Banner guard','banner',.97,1.44,'cloth','banner','blue'),
    ('Golem gauntlet','fist',1.12,1.14,'stone','knuckles','stone'),
    ('Patchwork barricade','broken',1.19,1.38,'wood','patches','wood'),
    ('Boat prow','prow',.99,1.67,'wood','prow','turquoise'),
    ('Thorn bramble','bramble',1.18,1.14,'leaf','thorns','green'),
    ('Phoenix feathers','phoenix',1.16,1.42,'metal','feathers','orange'),
    ('Frost antlers','antlers',1.18,1.45,'bone','antlers','ice'),
)

# name, shaft length, head type, head width, head height, shaft bend,
# construction, palette, wielding reference
AXES = (
    ('Woodcutters hatchet',.65,'hatchet',.30,.30,.035,'wood','iron','1H'),
    ('Carpenters beard',.82,'beard',.34,.42,-.035,'wood','bronze','1H'),
    ('Viking bearded axe',1.17,'deepbeard',.42,.58,.075,'wood','iron','1H'),
    ('Long Dane axe',1.94,'dane',.49,.61,-.06,'wood','cream','2H'),
    ('Francisca thrower',.69,'francisca',.36,.34,.15,'wood','bronze','1H'),
    ('Trail tomahawk',.81,'tomahawk',.31,.30,.025,'wood','turquoise','1H'),
    ('Pipe tomahawk',.94,'pipe',.29,.30,-.06,'wood','bronze','1H'),
    ('Pulaski fire axe',1.04,'pulaski',.42,.39,.08,'wood','red','2H'),
    ('Ships adze',.83,'adze',.32,.26,.14,'wood','iron','1H'),
    ('Double logging axe',1.24,'double',.36,.36,-.04,'wood','iron','2H'),
    ('War crescent',1.35,'crescent',.51,.64,.08,'metal','blue','2H'),
    ('Great double axe',1.85,'doublewide',.49,.60,.035,'metal','red','2H'),
    ('Pollaxe',2.02,'pollaxe',.35,.45,0,'wood','iron','2H'),
    ('Bardiche',1.92,'bardiche',.48,1.07,-.035,'wood','bronze','2H'),
    ('Crooked halberd',2.10,'halberd',.43,.60,.065,'wood','blue','2H'),
    ('Lochaber hook',1.99,'lochaber',.34,.88,.02,'wood','iron','2H'),
    ('Climbers pick',.87,'pick',.46,.24,.14,'metal','blue','1H'),
    ('Dwarven hammer axe',1.19,'hammer',.36,.43,-.10,'metal','gold','1H'),
    ('Flint stone axe',.90,'flint',.31,.37,-.14,'wood','stone','1H'),
    ('Tusk bone cleaver',1.41,'tusk',.51,.68,.13,'bone','cream','2H'),
    ('Crystal cleaver',1.25,'crystal',.42,.58,-.09,'metal','ice','1H'),
    ('Coral reef axe',1.12,'coral',.41,.47,.18,'bone','pink','1H'),
    ('Raptor claw axe',1.30,'claw',.46,.65,.10,'bone','cream','1H'),
    ('Clockwork cutter',1.12,'gear',.44,.48,0,'metal','bronze','1H'),
    ('Rootbound chopper',1.42,'root',.45,.56,-.17,'wood','green','2H'),
    ('Phoenix wing axe',1.72,'phoenix',.50,.68,.11,'metal','orange','2H'),
    ('Dragon twin fangs',1.78,'fangs',.41,.66,-.10,'bone','purple','2H'),
    ('Miners pickaxe',1.02,'pickaxe',.51,.32,.03,'wood','iron','2H'),
    ('Orchard billhook',.89,'billhook',.34,.52,.10,'wood','green','1H'),
    ('Crescent harvesting sickle',.67,'sickle',.45,.53,-.08,'wood','bronze','1H'),
    ('1H Reapers scythe',1.03,'scythe',.76,.38,.095,'wood','iron','1H'),
    ('1H Moon scythe',1.12,'moonscythe',.78,.44,-.12,'metal','purple','1H'),
    ('1H Thorn scythe',1.00,'thornscythe',.72,.44,.14,'wood','green','1H'),
    ('2H Harvest scythe',2.05,'scythe',1.02,.44,.21,'wood','bronze','2H'),
    ('2H Raven scythe',2.18,'ravenscythe',1.08,.53,-.14,'bone','purple','2H'),
    ('2H Solar scythe',2.30,'solarscythe',1.13,.55,.16,'metal','orange','2H'),
)

def equipment_name(family,variant):
    return (SHIELDS if family=='shield' else AXES)[int(variant)%36][0]

def equipment_visual(family,variant):
    return _visuals(family).get(int(variant)%36,{})

@lru_cache(maxsize=2)
def _visuals(family):
    path=Path(__file__).resolve().parents[1]/'qml/assets/authored/items'/f'weapon-{family}.variants.json'
    if not path.is_file():return {}
    return {r['variant']:r for r in json.loads(path.read_text())}
