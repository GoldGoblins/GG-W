"""Content-bank identities, independent of residency, camera and animation.

Curated sword, shield, axe, pistol and botanical rosters use individual constructions.
Older banks retain their six-by-six construction scheme. No model is generated
while playing.
"""
import hashlib

VARIANTS = 36
TREE_FAMILIES = ('oak','oak_arch','pine','jungle','palm','mangrove','deadwood')
WEAPON_FAMILIES = ('sword','pistol','whip','boomerang','shield','staff','wand','axe','spear','bow','mace','offhand')
TREE_DESIGNS = {
 'oak': ('umbrella','forked veteran','sweeping bough','hollow sentinel','candelabra','clustered saplings'),
 'oak_arch': ('low gateway','double arch','sideways giant','bridging roots','crooked loop','broken bow'),
 'jungle': ('buttress giant','layered canopy','twisted pillar','strangler crown','broad banana','kapok fan'),
 'mangrove': ('stilt roots','walking roots','twin tidal trunks','root basket','leaning brackish','low tidal thicket'),
 'pine': ('tiered spruce','bent fir','sweeping cedar','round juniper','forked conifer','windswept larch'),
 'palm': ('sea leaning coconut','splayed fan','forked island palm','corkscrew coconut','three trunk clump','pineapple dwarf'),
 'deadwood': ('lightning snag','driftwood arch','antler branches','hollow stump','fallen fork','split elder'),
}
SUBDESIGNS = ('wide low','high narrow','asymmetric shoulder','long curling tips','split silhouette','sparse open')
FLOWER_DESIGNS = ('open daisy','deep trumpet','hanging bell','layered rose','spire blossoms','star orchid')
WEAPON_DESIGNS = {
 'sword': ('cutlass','leaf blade','forked arc','cleaver','crescent saber','crystal thorn'),
 'pistol': ('flintlock','short blunderbuss','double barrel','crystal caster','pepperbox','curved rune pistol'),
 'whip': ('bullwhip','barbed vine','chain whip','ribbon lash','segmented tail','forked lash'),
 'boomerang': ('elbow','crescent','three wing','four wing','double hook','bat wing'),
 'shield': ('round buckler','kite','tower','crescent','leaf guard','shell'),
 'staff': ('crook','crescent','forked antler','spiral crystal','lantern','sun wheel'),
 'wand': ('star','thorn','shell spiral','feather','crystal fork','moon crescent'),
 'axe': ('woodcutter','double bit','crescent','stone beak','wide cleaver','thorn hook'),
 'spear': ('leaf point','trident','barbed harpoon','crescent pike','crystal lance','forked glaive'),
 'bow': ('longbow','recurve','horn bow','leaf bow','double limb','mechanical bow'),
}

def variant_for(identity):
    return int.from_bytes(hashlib.blake2s(str(identity).encode(),digest_size=4).digest(),'little') % VARIANTS

def stem(family, variant):
    return family + ('' if not variant else f'-v{variant}')

def design_name(family, variant):
    if family in ('wand','staff','mace','offhand'):
        from backend.game_engine_caster_designs import design
        return design(family,variant)['name']
    if family=='pistol':
        from backend.game_engine_pistol_designs import pistol_name
        return pistol_name(variant)
    if family in ('shield','axe'):
        from backend.game_engine_shield_axe_designs import equipment_name
        return equipment_name(family,variant)
    if family=='sword':
        from backend.game_engine_sword_designs import sword_name
        return sword_name(variant)
    from backend.game_engine_botanical_designs import botanical_name
    name=botanical_name(family,variant)
    if name:return name
    constructions=TREE_DESIGNS.get(family,WEAPON_DESIGNS.get(family,FLOWER_DESIGNS))
    return constructions[variant//6]+' / '+SUBDESIGNS[variant%6]
