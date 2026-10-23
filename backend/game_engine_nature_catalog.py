"""Original coastal species, habitats, tools and species-specific loot."""
from __future__ import annotations
import copy

PLANTS = {
    "sea_bell": ("Sea Bell", "flower", "COAST WETLAND", (.24,.64,.87)),
    "sun_daisy": ("Sun Daisy", "flower", "COAST MEADOW WOODLAND", (.96,.73,.16)),
    "moon_orchid": ("Moon Orchid", "orchid", "JUNGLE WETLAND", (.70,.35,.85)),
    "red_poppy": ("Ember Poppy", "flower", "MEADOW VOLCANIC", (.85,.20,.13)),
    "blue_lupin": ("Blue Lupin", "spire", "MEADOW TAIGA TUNDRA", (.30,.36,.84)),
    "berry_bush": ("Tideberry Bush", "bush", "COAST WOODLAND TAIGA", (.66,.15,.30)),
    "sage": ("Silver Sage", "herb", "COAST MEADOW VOLCANIC", (.45,.58,.43)),
    "broad_fern": ("Fan Fern", "fern", "WOODLAND JUNGLE WETLAND", (.22,.52,.19)),
    "aloe": ("Salt Aloe", "succulent", "COAST VOLCANIC", (.25,.62,.47)),
    "cattail": ("Marsh Reed", "reed", "WETLAND COAST", (.45,.26,.11)),
    "amanita": ("Scarlet Cap", "mushroom", "WOODLAND TAIGA JUNGLE", (.86,.22,.17)),
    "chanterelle": ("Golden Chanterelle", "mushroom", "WOODLAND MEADOW WETLAND", (.91,.57,.15)),
}
ANIMALS = {
    "rabbit": ("Dune Rabbit", "LAND", "COAST MEADOW", "rabbit", .54, (.64,.48,.29)),
    "squirrel": ("Copper Squirrel", "LAND", "WOODLAND TAIGA COAST", "squirrel", .45, (.64,.26,.10)),
    "hedgehog": ("Briar Hedgehog", "LAND", "WOODLAND MEADOW COAST", "hedgehog", .36, (.35,.25,.15)),
    "frog": ("Reed Frog", "LAND", "WETLAND JUNGLE COAST", "frog", .26, (.22,.61,.22)),
    "lizard": ("Sun Lizard", "LAND", "COAST VOLCANIC JUNGLE", "lizard", .39, (.28,.65,.43)),
    "crab": ("Shore Crab", "LAND", "COAST WETLAND", "crab", .42, (.79,.28,.14)),
    "boar": ("Bristle Boar", "LAND", "WOODLAND JUNGLE MEADOW", "boar", 1.18, (.35,.23,.14)),
    "fox": ("Amber Fox", "LAND", "WOODLAND TAIGA MEADOW", "fox", .92, (.76,.35,.14)),
    "goat": ("Cliff Goat", "LAND", "COAST TAIGA TUNDRA MEADOW", "goat", 1.25, (.73,.65,.46)),
    "sheep": ("Cloud Sheep", "LAND", "COAST MEADOW WOODLAND", "sheep", 1.12, (.85,.81,.65)),
    "sunfin": ("Sunfin", "WATER", "OCEAN COAST", "fish", .40, (.89,.58,.14)),
    "reef_perch": ("Reef Perch", "WATER", "OCEAN COAST", "fish", .55, (.24,.57,.72)),
    "needlefish": ("Silver Needlefish", "WATER", "OCEAN COAST", "needlefish", .75, (.56,.73,.76)),
    "lanternfish": ("Lanternfish", "WATER", "OCEAN COAST", "lanternfish", .35, (.35,.31,.68)),
    "puffer": ("Gold Puffer", "WATER", "OCEAN COAST", "puffer", .44, (.86,.66,.27)),
    "turtle": ("Mossback Turtle", "WATER", "OCEAN COAST", "turtle", .85, (.29,.50,.32)),
    "octopus": ("Violet Octopus", "WATER", "OCEAN COAST", "octopus", .70, (.58,.31,.56)),
    "gull": ("Coastal Gull", "AIR", "COAST WETLAND", "bird", .65, (.85,.87,.78)),
    "songbird": ("Azure Songbird", "AIR", "WOODLAND MEADOW COAST", "bird", .26, (.24,.53,.82)),
    "parrot": ("Jade Parrot", "AIR", "JUNGLE WETLAND COAST", "parrot", .52, (.25,.66,.32)),
    "bee": ("Amber Bee", "AIR", "COAST MEADOW WOODLAND", "bee", .14, (.93,.65,.14)),
    "butterfly": ("Moonwing Butterfly", "AIR", "COAST JUNGLE MEADOW", "butterfly", .24, (.53,.30,.77)),
}
TOOLS = {"shears":"Gatherer's Shears", "bucket":"Milk Pail", "brush":"Soft Brush",
         "net":"Critter Net", "rod":"Reed Fishing Rod", "knife":"Skinning Knife"}
PRODUCE = {
    'coconut': ('Coconut','fruit_coconut','COAST',(.49,.28,.11)),
    'banana': ('Banana','fruit_banana','JUNGLE WETLAND COAST',(.95,.75,.16)),
    'apple': ('Apple','fruit_apple','WOODLAND MEADOW',(.86,.18,.12)),
    'pineapple': ('Pineapple','fruit_pineapple','COAST JUNGLE',(.90,.63,.12)),
    'grapes': ('Grapes','fruit_grapes','WOODLAND JUNGLE MEADOW',(.42,.22,.63)),
    'juniper': ('Juniper Berries','fruit_juniper','TAIGA TUNDRA MEADOW',(.24,.34,.55)),
}
PLANTS.update(PRODUCE)
PLANTS.update({
 'moon_lily':('Moon Lily','flower','WETLAND JUNGLE',(.88,.81,.96)),
 'ember_tulip':('Ember Tulip','flower','MEADOW VOLCANIC',(.94,.31,.17)),
 'wind_iris':('Wind Iris','orchid','MEADOW WETLAND',(.43,.36,.87)),
 'marigold':('Golden Marigold','flower','COAST MEADOW',(.98,.65,.10)),
 'velvet_rose':('Velvet Rose','flower','WOODLAND MEADOW',(.83,.23,.40)),
 'sky_delphinium':('Sky Delphinium','spire','MEADOW TAIGA',(.21,.57,.89)),
 'foxglove':('Twilight Foxglove','spire','WOODLAND TAIGA',(.65,.32,.74)),
 'lavender':('Silver Lavender','herb','MEADOW COAST',(.63,.52,.86)),
 'clover':('Meadow Clover','herb','MEADOW WOODLAND',(.82,.63,.83)),
 'ivy':('Climbing Ivy','fern','WOODLAND JUNGLE',(.21,.49,.23)),
 'grape_vine':('Grape Vine','bush','WOODLAND MEADOW JUNGLE',(.46,.22,.66)),
 'juniper_bush':('Juniper Bush','bush','TAIGA TUNDRA',(.25,.37,.58)),
 'pineapple_rosette':('Pineapple Rosette','succulent','COAST JUNGLE',(.93,.69,.16)),
})
ANIMALS.update({
 'deer':('Meadow Deer','LAND','MEADOW WOODLAND','goat',1.42,(.65,.38,.20)),
 'badger':('Honey Badger','LAND','WOODLAND MEADOW','boar',.66,(.35,.35,.31)),
 'otter':('River Otter','LAND','WETLAND COAST','lizard',.65,(.46,.29,.15)),
 'raccoon':('Bandit Raccoon','LAND','WOODLAND COAST','fox',.70,(.46,.44,.38)),
 'porcupine':('Bristle Porcupine','LAND','WOODLAND JUNGLE','hedgehog',.71,(.44,.28,.14)),
 'armadillo':('Dune Armadillo','LAND','VOLCANIC COAST','boar',.67,(.57,.47,.31)),
 'fennec':('Dune Fennec','LAND','VOLCANIC COAST','fox',.52,(.87,.67,.35)),
 'owl':('Duskwatch Owl','AIR','WOODLAND TAIGA','bird',.59,(.60,.44,.28)),
 'toucan':('Mango Toucan','AIR','JUNGLE WETLAND','parrot',.64,(.25,.29,.37)),
 'kingfisher':('Azure Kingfisher','AIR','WETLAND COAST','bird',.34,(.17,.64,.77)),
 'falcon':('Ridge Falcon','AIR','TAIGA TUNDRA MEADOW','bird',.67,(.57,.51,.41)),
 'hummingbird':('Emerald Hummingbird','AIR','JUNGLE MEADOW','bird',.18,(.24,.74,.45)),
 'koi':('Amber Koi','WATER','COAST WETLAND','fish',.66,(.88,.45,.18)),
 'angler':('Deep Angler','WATER','OCEAN COAST','lanternfish',.63,(.35,.27,.50)),
 'ray':('Azure Ray','WATER','OCEAN COAST','fish',1.10,(.27,.56,.70)),
 'shark':('Reef Shark','WATER','OCEAN COAST','needlefish',1.60,(.38,.52,.61)),
 'seahorse':('Coral Seahorse','WATER','OCEAN COAST','fish',.39,(.91,.55,.23)),
 'jellyfish':('Moon Jellyfish','WATER','OCEAN COAST','octopus',.62,(.58,.53,.81)),
})
LABELS = {"PICK":"Pick", "CLIP":"Clip", "SHEAR":"Shear wool", "MILK":"Milk",
          "BRUSH":"Brush", "CATCH":"Catch", "FISH":"Fish", "LOOT":"Loot remains",
          "SKIN":"Collect hide", "PET":"Pet", "ATTACK":"Hunt"}


def species_catalog():
    out={}
    for key,(name,shape,habitats,color) in PLANTS.items():
        resource={'grape_vine':'grapes','juniper_bush':'juniper','pineapple_rosette':'pineapple'}.get(key,key)
        action="CLIP" if shape in {"fern","reed","herb"} else "PICK"
        out[key]={"id":key,"name":name,"domain":"PLANT","shape":shape,
                  "biomes":habitats.split(),"size":.7,"color":color,"health":1,
                  "actions":{action:{"tool":"shears" if action=="CLIP" else "", "cooldown_s":180,
                                     "resource":resource,"quantity":(1,3)}}}
    for key,(name,domain,habitats,shape,size,color) in ANIMALS.items():
        actions={"LOOT":{"tool":"","cooldown_s":300,"resource":key+"_meat","quantity":(1,2),"dead":True},
                 "PET":{"tool":"","cooldown_s":2,"resource":"","quantity":(0,0)}}
        if domain=="LAND":
            actions["SKIN"]={"tool":"knife","cooldown_s":300,"resource":key+"_hide","quantity":(1,2),"dead":True}
        if key=="sheep":actions["SHEAR"]={"tool":"shears","cooldown_s":120,"resource":"cloud_wool","quantity":(2,4)}
        if key=="goat":actions["MILK"]={"tool":"bucket","cooldown_s":90,"resource":"cliff_milk","quantity":(1,2)}
        if key in {"rabbit","fox","squirrel"}:actions["BRUSH"]={"tool":"brush","cooldown_s":90,"resource":key+"_fur","quantity":(1,2)}
        if key in {"gull","songbird","parrot"}:actions["BRUSH"]={"tool":"brush","cooldown_s":90,"resource":key+"_feather","quantity":(1,2)}
        if key in {"frog","lizard","crab","bee","butterfly","octopus","turtle"}:
            actions["CATCH"]={"tool":"net","cooldown_s":300,"resource":"live_"+key,"quantity":(1,1),"remove":True}
        if domain=="WATER" and key not in {"octopus","turtle"}:
            actions["FISH"]={"tool":"rod","cooldown_s":180,"resource":"fresh_"+key,"quantity":(1,2),"remove":True}
        out[key]={"id":key,"name":name,"domain":domain,"shape":shape,"biomes":habitats.split(),
                  "size":size,"color":color,"health":3 if size<.6 else 8,"actions":actions}
    for key,s in out.items():
        s["loot_table_id"]="loot.nature."+key
        for action,a in s["actions"].items():
            a["label"]=LABELS[action];a["table_id"]="loot.nature."+key+"."+action.lower()
    return out


SPECIES=species_catalog()


def item_definitions(template):
    resources={}
    for key,s in SPECIES.items():
        for a in s["actions"].values():
            if a["resource"]:resources[a["resource"]]=s["name"] if a["resource"]==key else a["resource"].replace("_"," ").title()
        resources[key+"_rare"]=s["name"]+" Pristine Specimen"
    out={}
    for key,name in {**resources,**{("tool_"+k):v for k,v in TOOLS.items()}}.items():
        row=copy.deepcopy(template)
        row.update(id="item.nature."+key,name=name,kind="TOOL" if key.startswith("tool_") else "MATERIAL",
                   rarity="UNCOMMON" if key.endswith("_rare") else "COMMON",stack_limit=1 if key.startswith("tool_") else 99,
                   equip_slot="",tags=["NATURE", "TOOL" if key.startswith("tool_") else "RESOURCE"])
        row.pop("gear",None)
        if key.startswith("tool_"):
            asset_id="itemmesh.nature."+key
            row["asset_id"]=asset_id
            row["visual"]["asset_id"]=asset_id
            for state in row["visual"].get("states",{}).values():
                state["asset_id"]=asset_id
        elif key in PRODUCE:
            asset_id='itemmesh.nature.'+key
            row.update(asset_id=asset_id,tags=['NATURE','RESOURCE','FOOD','COOKING'])
            row['visual']['asset_id']=asset_id
            for state in row['visual'].get('states',{}).values():state['asset_id']=asset_id
        out[row["id"]]=row
    return out


def loot_tables():
    tables={}
    for key,s in SPECIES.items():
        for action,a in s["actions"].items():
            if not a["resource"]:continue
            table={"id":a["table_id"],"name":s["name"]+" · "+a["label"],"entries":[
                {"item_id":"item.nature."+a["resource"],"weight":94,"min":a["quantity"][0],"max":a["quantity"][1]},
                {"item_id":"item.nature."+key+"_rare","weight":6,"min":1,"max":1}]}
            tables[table["id"]]=table
        first=next((a for a in s["actions"].values() if a["resource"]),None)
        tables[s["loot_table_id"]]={**copy.deepcopy(tables[first["table_id"]]),"id":s["loot_table_id"]}
    return tables
