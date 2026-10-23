"""Curated 36-slot botanical banks; every slot has a deliberate species design."""
FLOWERS=(
 ('Prästkrage','daisy',(1,.96,.86),.58,1),
 ('Maskros','dandelion',(1,.78,.08),.32,1),
 ('Röd ros','rose',(.86,.10,.14),.80,1),
 ('Rosa ros','rose',(.97,.42,.61),.60,3),
 ('Röd tulpan','tulip',(.94,.16,.12),.58,1),
 ('Gul tulpan','tulip',(1,.83,.12),.42,2),
 ('Vallmo','poppy',(.97,.22,.10),.67,2),
 ('Blåklint','cornflower',(.19,.40,.94),.56,3),
 ('Solros','sunflower',(1,.75,.07),1.28,1),
 ('Lavendel','lavender',(.61,.40,.79),.63,5),
 ('Tigerlilja','lily',(1,.47,.13),.90,3),
 ('Vit kalla','calla',(1,.97,.87),.68,1),
 ('Lila iris','iris',(.49,.27,.74),.75,1),
 ('Blå iris','iris',(.20,.48,.85),.63,2),
 ('Rosa orkidé','orchid',(.96,.47,.68),.78,3),
 ('Vit orkidé','orchid',(.97,.97,.90),.55,2),
 ('Påsklilja','daffodil',(1,.87,.25),.48,2),
 ('Förgätmigej','forget_me_not',(.32,.69,.98),.26,7),
 ('Pion','peony',(.96,.56,.66),.59,1),
 ('Vit dahlia','dahlia',(1,.93,.82),.69,1),
 ('Korallfärgad dahlia','dahlia',(.99,.37,.29),.83,3),
 ('Pensé','pansy',(.45,.27,.73),.22,3),
 ('Hibiskus','hibiscus',(.93,.15,.24),.82,2),
 ('Blå hortensia','hydrangea',(.39,.64,.95),.63,3),
 ('Fingerborgsblomma','foxglove',(.83,.31,.55),1.03,1),
 ('Riddarsporre','delphinium',(.40,.44,.86),1.12,2),
 ('Rosenskära','cosmos',(.98,.49,.64),.81,3),
 ('Vitsippa','anemone',(.99,.98,.91),.25,2),
 ('Liljekonvalj','lily_valley',(1,.98,.91),.37,1),
 ('Blåklocka','bluebell',(.38,.51,.85),.48,4),
 ('Rödklöver','clover',(.85,.41,.65),.27,3),
 ('Lejongap','snapdragon',(.96,.25,.30),.82,2),
 ('Tagetes','marigold',(1,.55,.08),.36,3),
 ('Zinnia','zinnia',(.90,.22,.52),.59,2),
 ('Pelargon','geranium',(.93,.24,.28),.39,4),
 ('Snödroppe','snowdrop',(.97,.99,.94),.24,2),
)
TREES=(
 ('Björk','birch',7.8,2.7,(.88,.88,.77),(.51,.67,.25)),
 ('Asp','aspen',8.5,2.0,(.69,.73,.63),(.87,.74,.24)),
 ('Lönn','maple',7.0,3.7,(.40,.28,.18),(.90,.37,.13)),
 ('Bok','beech',8.2,3.0,(.49,.49,.40),(.41,.59,.19)),
 ('Ek','oak',6.5,4.1,(.33,.23,.13),(.29,.48,.17)),
 ('Bergek','sessile_oak',8.0,3.2,(.39,.27,.18),(.40,.51,.16)),
 ('Pil','willow',6.9,3.7,(.41,.36,.22),(.61,.69,.23)),
 ('Poppel','poplar',10.0,1.6,(.54,.53,.43),(.44,.61,.26)),
 ('Alm','elm',8.4,3.7,(.37,.29,.19),(.43,.59,.20)),
 ('Ask','ash',8.7,3.1,(.50,.47,.36),(.56,.66,.28)),
 ('Hästkastanj','chestnut',6.8,3.9,(.40,.29,.19),(.27,.46,.22)),
 ('Lind','linden',7.5,3.1,(.45,.36,.22),(.67,.72,.23)),
 ('Rönn','rowan',5.7,2.3,(.47,.43,.32),(.54,.60,.28)),
 ('Al','alder',7.1,2.6,(.43,.42,.32),(.28,.46,.25)),
 ('Avenbok','hornbeam',7.6,2.5,(.55,.54,.43),(.51,.62,.26)),
 ('Körsbärsblom','cherry',5.8,3.5,(.36,.23,.19),(.98,.61,.70)),
 ('Äppelträd','apple',5.0,2.9,(.37,.27,.17),(.47,.62,.23)),
 ('Prydnadsapel','crabapple',4.2,2.1,(.44,.31,.22),(.94,.65,.66)),
 ('Päronträd','pear',6.1,2.5,(.43,.31,.20),(.54,.65,.30)),
 ('Gran','spruce',9.0,2.7,(.39,.24,.14),(.16,.37,.28)),
 ('Ädelgran','fir',8.3,3.1,(.44,.35,.25),(.24,.47,.37)),
 ('Tall','pine',8.0,3.5,(.61,.35,.17),(.31,.46,.25)),
 ('Ceder','cedar',7.4,4.0,(.46,.28,.16),(.24,.48,.39)),
 ('Lärk','larch',8.0,2.2,(.39,.29,.21),(.80,.68,.20)),
 ('Cypress','cypress',9.5,1.3,(.39,.32,.24),(.19,.38,.23)),
 ('Sekvoja','sequoia',11.3,3.0,(.60,.27,.14),(.24,.44,.24)),
 ('Baobab','baobab',6.4,3.5,(.53,.40,.30),(.45,.58,.24)),
 ('Jakaranda','jacaranda',6.5,3.7,(.40,.30,.23),(.59,.43,.81)),
 ('Akacia','acacia',6.5,4.5,(.47,.32,.17),(.57,.64,.24)),
 ('Magnolia','magnolia',5.8,2.9,(.41,.31,.23),(.28,.47,.32)),
 ('Robinia','locust',7.4,3.2,(.44,.32,.21),(.55,.64,.29)),
 ('Banyan','banyan',7.0,4.3,(.51,.36,.24),(.30,.51,.25)),
 ('Kokospalm','coconut',7.5,3.8,(.55,.34,.18),(.42,.60,.22)),
 ('Solfjäderspalm','fan_palm',6.5,3.0,(.45,.30,.18),(.45,.64,.25)),
 ('Bananträd','banana',4.3,3.0,(.56,.64,.22),(.40,.62,.22)),
 ('Mangrove','mangrove',5.9,3.3,(.44,.34,.24),(.39,.55,.25)),
)
FOLIAGE=(
 ('Monstera','monstera',( .24,.48,.24),1.0),
 ('Gummifikus','ficus_elastica',(.20,.40,.24),1.45),
 ('Benjaminfikus','ficus_benjamina',(.44,.63,.28),1.7),
 ('Japansk solfjäderspalm','fan_palm',(.42,.61,.25),1.2),
 ('Bambu','bamboo',(.36,.60,.22),2.0),
 ('Guldbambu','gold_bamboo',(.68,.72,.23),1.7),
 ('Spjutbräken','boston_fern',(.37,.61,.26),.7),
 ('Venushår','maidenhair',(.54,.69,.31),.55),
 ('Örnbräken','bracken',(.39,.54,.19),1.0),
 ('Fågelbobräken','birdnest',(.53,.68,.27),.65),
 ('Kaladium','caladium',(.89,.36,.47),.76),
 ('Palettblad','coleus',(.65,.27,.51),.69),
 ('Funkia','hosta',(.48,.66,.38),.58),
 ('Bananplanta','banana',(.43,.63,.23),1.3),
 ('Elefantöra','elephant_ear',(.34,.54,.30),1.1),
 ('Papyrus','papyrus',(.44,.64,.29),1.2),
 ('Starr','sedge',(.61,.67,.31),.70),
 ('Fräken','horsetail',(.39,.59,.32),.80),
 ('Tåg','rush',(.44,.58,.34),.62),
 ('Kaveldun','cattail',(.51,.64,.31),1.2),
 ('Rosmarin','rosemary',(.40,.55,.41),.55),
 ('Timjan','thyme',(.49,.62,.35),.22),
 ('Salvia','sage',(.59,.68,.50),.46),
 ('Mynta','mint',(.32,.61,.31),.58),
 ('Brännässla','nettle',(.47,.61,.24),.87),
 ('Murgröna','ivy',(.25,.48,.26),1.08),
 ('Vinranka','grapevine',(.47,.59,.25),1.22),
 ('Vildvin','creeper',(.76,.37,.24),1.05),
 ('Mossa','moss',(.50,.62,.25),.10),
 ('Ljung','heather',(.73,.40,.60),.54),
 ('Enbuske','juniper',(.34,.48,.40),.73),
 ('Kottepalm','cycas',(.35,.52,.24),.94),
 ('Yucca','yucca',(.58,.69,.35),.85),
 ('Aloe vera','aloe',(.47,.65,.43),.52),
 ('Agave','agave',(.43,.62,.59),.77),
 ('Fikonkaktus','cactus',(.45,.61,.34),.98),
)
TREE_VARIANTS={
 'oak':tuple(range(19))+(29,30),
 'oak_arch':(0,2,4,5,6,8,9,10,13,14,16),
 'pine':(19,20,21,22,23,24,25),
 'jungle':(26,27,28,29,30,31,34),
 'palm':(32,33), 'mangrove':(35,),
}

def tree_variant(identity,family):
    from backend.game_engine_asset_variations import variant_for
    choices=TREE_VARIANTS.get(family)
    return choices[variant_for(identity)%len(choices)] if choices else variant_for(identity)

FOLIAGE_BIOMES={
 'COAST':(3,13,16,18,19,28,31,32,33,34),
 'WOODLAND':(6,7,8,9,12,16,20,21,22,23,24,25,28,29,30),
 'MEADOW':(12,16,18,20,21,22,23,24,28,29),
 'TAIGA':(6,8,16,20,21,28,29,30),
 'TUNDRA':(16,21,28,29,30),
 'JUNGLE':(0,1,2,3,4,5,6,7,9,10,11,13,14,25,26,31),
 'WETLAND':(4,6,8,9,14,15,16,17,18,19,25,28),
 'VOLCANIC':(20,21,28,32,33,34,35),
}

def foliage_variant(identity,family,biome):
    from backend.game_engine_asset_variations import variant_for
    if family not in ('fern','scrub','grass'):return variant_for(identity)
    choices=FOLIAGE_BIOMES.get(biome,tuple(range(36)))
    if family=='grass':
        preferred=tuple(v for v in choices if v in (13,15,16,17,18,19,21,28,32))
    elif family=='scrub':
        preferred=tuple(v for v in choices if v in (1,2,3,10,11,20,21,22,23,24,29,30,31,33,34,35))
    else:
        preferred=tuple(v for v in choices if v in (0,4,5,6,7,8,9,12,14,25,26,28))
    choices=preferred or choices
    return choices[variant_for(identity)%len(choices)]

def botanical_name(family,variant):
    if family in TREE_VARIANTS:return TREES[variant][0]
    if family=='flowers':return FLOWERS[variant][0]
    if family in ('fern','scrub','grass'):return FOLIAGE[variant][0]
    return None
