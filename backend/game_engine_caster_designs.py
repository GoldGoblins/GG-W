"""Curated, original equipment identities shared by Blender and the engine.

Every row selects a construction, proportions and an optional magic core.
Display galleries never determine item identity, position or hand rules.
"""
import json
from functools import lru_cache
from pathlib import Path

THEMES = {
    'none': [], 'fire': ['#ff7038','#ffd36b'], 'frost': ['#6edaff','#e0fbff'],
    'nature': ['#8fe258','#e8ef83'], 'arcane': ['#ba76ff','#f3b9ff'],
    'storm': ['#57dfea','#eefbff'], 'holy': ['#ffe18a','#fff5d6'],
    'shadow': ['#dd64b9','#8455dc'], 'water': ['#4dd7c0','#b5f6e7'],
}

def _roster(text, wield):
    result=[]
    for line in text.strip().splitlines():
        name,kind,length,radius,bend,material,palette,theme=line.split('|')
        result.append(dict(name=name,construction=kind,length=float(length),radius=float(radius),
            bend=float(bend),material=material,palette=palette,theme=theme,
            colors=THEMES[theme],wielding_reference=wield))
    assert len(result)==36 and len({r['name'] for r in result})==36
    return tuple(result)

WANDS=_roster('''
Hazel apprentice|plain|.54|.035|.025|wood|wood|none
Elder knot|knot|.62|.043|-.065|wood|wood|none
Briar thorn|thorn|.64|.039|.12|wood|green|nature
Willow leaf|leaf|.67|.032|-.11|wood|green|nature
Forked rowan|twig|.58|.04|.09|wood|red|none
Stag tine|antler|.71|.037|-.075|bone|cream|nature
Raven feather|feather|.69|.028|.06|bone|purple|shadow
Carved ivory|bone|.61|.046|-.035|bone|cream|none
Amethyst needle|crystal|.63|.032|.055|crystal|purple|arcane
Winter icicle|icicle|.73|.028|-.055|crystal|ice|frost
Fivepoint star|star|.56|.032|.035|metal|gold|holy
Midnight moon|moon|.66|.03|-.07|metal|purple|shadow
Sunflower sun|sun|.58|.033|.045|metal|gold|holy
Coiled serpent|snake|.65|.038|.13|wood|green|nature
Watcher eye|eye|.55|.039|-.035|bone|purple|shadow
Clocktower key|key|.61|.031|0|metal|bronze|arcane
Storm tuning fork|fork|.68|.03|-.03|metal|blue|storm
Copper induction coil|coil|.59|.035|.025|metal|bronze|storm
Ember match|torch|.57|.041|-.055|wood|orange|fire
Firefly lantern|lantern|.64|.029|.04|metal|turquoise|nature
Silver bell|bell|.53|.033|-.025|metal|iron|holy
Spiral conch|shell|.57|.041|.08|bone|pink|water
Red coral sprig|coral|.63|.032|-.09|bone|pink|water
Kraken curl|tentacle|.70|.042|.16|bone|turquoise|water
Toadstool spore|mushroom|.49|.037|-.055|wood|red|nature
Orchid bloom|flower|.63|.025|.055|wood|pink|nature
Acorn keeper|seed|.56|.034|-.035|wood|reed|nature
Brass cog|cog|.58|.032|.025|metal|bronze|arcane
Split glass prism|prism|.67|.03|-.035|crystal|turquoise|arcane
Scribes quill|quill|.75|.025|.07|bone|cream|arcane
Runescript baton|scroll|.57|.039|0|wood|blue|arcane
Wind chimes|chime|.63|.03|.04|metal|iron|storm
Dragon fang|dragon|.71|.046|-.10|bone|orange|fire
Phoenix plume|wing|.74|.032|.14|metal|orange|fire
Starlit comet|comet|.66|.028|-.06|metal|blue|arcane
Crooked orchard crook|crook|.70|.042|.12|wood|wood|none
''','1H')

STAVES=_roster('''
Ash quarterstaff|plain|2.10|.055|.025|wood|wood|none
Travellers walking stick|walking|1.86|.069|-.16|wood|wood|none
Shepherds crook|crook|2.18|.056|.14|wood|reed|none
Old wizards rootlight|wizard|2.24|.076|-.18|wood|wood|holy
Living rootheart|root|2.31|.081|.25|wood|green|nature
Great stag antlers|antler|2.38|.065|-.12|bone|cream|nature
Sage branchfork|twig|2.05|.083|.19|wood|wood|none
Ginkgo canopy|leaf|2.13|.059|-.17|wood|green|nature
Lotus of the marsh|flower|1.98|.060|.13|wood|pink|water
Fungal shepherd|mushroom|1.89|.082|-.14|wood|red|nature
Bamboo pilgrim|bamboo|2.33|.065|.055|wood|reed|none
Threeface totem|totem|2.19|.079|-.075|wood|red|shadow
Ivory ossuary|bone|2.42|.065|.09|bone|cream|shadow
Serpents sceptre|snake|2.25|.059|-.19|metal|green|nature
Dragonjaw inferno|dragon|2.48|.085|.15|bone|orange|fire
Tide callers conch|shell|2.03|.068|-.12|bone|pink|water
Reef coral crown|coral|2.29|.065|.23|bone|pink|water
Abyssal trident|trident|2.56|.053|-.07|metal|turquoise|water
Spiral of the forest|spiral|2.15|.075|.22|wood|wood|nature
Amethyst geode|crystal|2.37|.057|-.09|crystal|purple|arcane
Glacier spear|icicle|2.59|.052|.085|crystal|ice|frost
Solar processional|sun|2.28|.065|0|metal|gold|holy
Waning moon|moon|2.45|.056|-.13|metal|purple|shadow
Astral wayfinder|star|2.12|.056|.09|metal|blue|arcane
Watchmans lantern|lantern|2.34|.062|.20|wood|wood|fire
Incense censer|censer|2.04|.067|-.15|metal|bronze|holy
Clockwork escapement|clock|2.22|.061|.065|metal|bronze|arcane
Celestial astrolabe|astrolabe|2.53|.054|-.08|metal|blue|arcane
Twin prism fork|prism|2.39|.057|.12|crystal|turquoise|arcane
Ritual bonfire|torch|2.11|.082|-.10|wood|orange|fire
Phoenix wing standard|wing|2.62|.065|.19|metal|orange|fire
Gatekeepers great key|key|2.17|.063|0|metal|iron|arcane
Windsong banner|banner|2.46|.057|-.06|cloth|blue|none
Mountain wind chimes|chime|2.32|.052|.11|metal|iron|storm
Thundercloud fork|fork|2.55|.056|-.08|metal|blue|storm
Sages curling seedpod|sage|2.21|.080|.24|wood|green|nature
''','2H')

MACES=_roster('''
Knotted cudgel|cudgel|.71|.045|.08|wood|wood|none
Bronze knob mace|knob|.76|.043|-.035|metal|bronze|none
Sixflange iron mace|flange|.84|.036|0|metal|iron|none
Short morning star|spiked|.79|.046|-.045|metal|iron|none
Stonewood crusher|stone|.88|.049|.095|stone|stone|none
Hookbeak warhammer|warhammer|.85|.035|-.03|metal|iron|none
Ravens beak war pick|beak|.91|.038|.045|metal|iron|none
Chained iron flail|flail|.77|.041|.035|metal|iron|none
Priests sun mace|sun|.93|.042|-.045|metal|gold|holy
Templars cross|cross|1.02|.038|.03|metal|blue|holy
Carved bone club|bone|.86|.049|-.075|bone|cream|none
Jungle root mallet|root|.97|.057|.12|wood|green|nature
Crystal basalt mace|crystal|.96|.039|-.045|stone|purple|arcane
Coral sea hammer|coral|.92|.05|.085|bone|pink|water
Goblin cog knocker|cog|.81|.041|0|metal|bronze|none
Dragon tooth cudgel|dragon|1.06|.053|-.08|bone|orange|fire
Frostbell mace|bell|.91|.041|.045|metal|ice|frost
Acorn hedgehog|seed|.87|.05|-.065|wood|green|nature
Great timber maul|maul|1.94|.088|.075|wood|wood|none
Warriors slabhammer|slab|2.08|.072|-.045|metal|iron|none
Cathedral war hammer|cathedral|2.22|.064|0|metal|gold|holy
Long starcrusher|greatstar|2.04|.069|.04|metal|iron|none
Ogres boulder club|boulder|1.86|.105|-.13|stone|stone|none
Giants flanged mace|greatflange|2.27|.067|.025|metal|red|none
Ironwood stump mallet|stump|1.98|.084|.16|wood|wood|nature
Antler thundermaul|antler|2.39|.069|-.10|bone|cream|storm
Moonring greatmace|moon|2.16|.065|.08|metal|purple|shadow
Obsidian obelisk|obelisk|2.30|.064|-.07|stone|purple|shadow
Forge engine hammer|engine|2.10|.077|0|metal|bronze|fire
Twin ram hammer|ram|2.42|.071|.06|bone|cream|none
Coral reef crusher|reef|2.01|.074|-.15|bone|pink|water
Frozen glacier maul|glacier|2.36|.061|.08|crystal|ice|frost
Solar judgement|judgement|2.54|.073|0|metal|gold|holy
Rootbound fist|fist|2.12|.092|.18|wood|green|nature
Meteor bellbreaker|meteor|2.45|.071|-.075|stone|orange|fire
Mountain gong hammer|gong|2.29|.067|.05|metal|bronze|storm
''','1H')
MACES=tuple(dict(row,wielding_reference='1H' if i<18 else '2H') for i,row in enumerate(MACES))

OFFHANDS=_roster('''
Apprentices stitched tome|book|.46|.18|0|hide|wood|none
Crimson clasp grimoire|claspbook|.55|.22|0|hide|red|fire
Moonbound codex|moonbook|.50|.20|0|hide|purple|shadow
Living leaf journal|leafbook|.48|.18|0|leaf|green|nature
Crystal atlas|atlas|.59|.24|0|crystal|blue|arcane
Open rune scripture|openbook|.48|.26|0|hide|cream|holy
Witches ragged spellbook|raggedbook|.54|.24|0|hide|purple|shadow
Small brass pocketbook|pocketbook|.34|.14|0|metal|bronze|none
Rolled vellum scroll|scroll|.44|.08|0|cloth|cream|none
Unfurled fire scripture|unfurled|.57|.17|0|cloth|red|fire
Twin scroll reliquary|twinscroll|.52|.10|0|metal|blue|arcane
Map of the tides|map|.50|.23|0|cloth|turquoise|water
Clear sky orb|orb|.37|.16|0|crystal|ice|frost
Clawed void sphere|claworb|.49|.20|0|bone|purple|shadow
Bronze armillary globe|armillary|.59|.23|0|metal|bronze|arcane
Root cradled seedlight|rootorb|.44|.18|0|wood|green|nature
Pearl on a shell|pearl|.38|.17|0|bone|pink|water
Old harbour lantern|lantern|.60|.18|0|metal|iron|fire
Firefly cage|cage|.55|.18|0|wood|green|nature
Moon glass lantern|moonlamp|.65|.20|0|metal|purple|shadow
Pilgrims candle|candle|.41|.13|0|metal|gold|holy
Dragon oil lamp|oillamp|.40|.19|0|metal|bronze|fire
Threeflame candelabra|candles|.61|.23|0|metal|gold|holy
Saints chalice|chalice|.52|.17|0|metal|gold|holy
Storm hourglass|hourglass|.58|.19|0|metal|blue|storm
Ritual skull|skull|.40|.19|0|bone|cream|shadow
Tribal spirit mask|mask|.56|.21|0|wood|red|shadow
Pocket ancestor totem|totem|.57|.16|0|wood|green|nature
Broken rune tablet|tablet|.52|.21|0|stone|stone|arcane
Golden sun relic|sunrelic|.49|.20|0|metal|gold|holy
Silver moon sickle|moonrelic|.56|.20|0|metal|purple|shadow
Navigator astrolabe|astrolabe|.61|.23|0|metal|bronze|arcane
Singing crystal cluster|crystals|.50|.19|0|crystal|ice|frost
Tidecallers conch|conch|.45|.20|0|bone|pink|water
Phoenix feather fan|fan|.63|.24|0|bone|orange|fire
Herbalist seed basket|basket|.46|.22|0|woven|reed|nature
''','OFF_HAND')

BANKS={'wand':WANDS,'staff':STAVES,'mace':MACES,'offhand':OFFHANDS}

def design(family,variant):
    return BANKS[family][int(variant)%36]

@lru_cache(maxsize=4)
def _visuals(family):
    p=Path(__file__).resolve().parents[1]/'qml/assets/authored/items'/f'weapon-{family}.variants.json'
    return {r['variant']:r for r in json.loads(p.read_text())} if p.is_file() else {}

def equipment_visual(family,variant):
    return _visuals(family).get(int(variant)%36,{})

def wand_profile(variant):
    row=design('wand',variant);theme=row['theme']
    effects={'fire':('burn',1.6,3),'frost':('slow',.22,2),'nature':('poison',.8,3),
        'storm':('shock',2,0),'shadow':('lifesteal',.07,0),'water':('weaken',.10,2)}
    status=effects.get(theme)
    return dict(range_m=34 if theme in ('arcane','storm') else 30,
        damage=12 if theme in ('fire','shadow') else 10,cooldown_s=1.25 if theme in ('fire','shadow') else 1.05,
        colors=list(row['colors'] or ['#e7ddc9']),
        status_effects=[dict(kind=status[0],amount=status[1],duration_s=status[2],source_id='wand.'+theme)] if status else [])
