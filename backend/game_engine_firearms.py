"""Server-owned firearm rules and persistent magazines for 36 authored guns.

Damage uses the engine's checked target/line-of-sight hit system. Projectile
trails are presentation effects, not an unbounded rigid-body simulation.
"""
import math
from backend.game_engine_pistol_designs import PISTOLS,TWO_HANDED,SUBTYPES
from backend.game_engine_asset_variations import variant_for

# slug, name, visible projectile/FX colour, original mesh construction
AMMO={slug:dict(id='item.ammo_'+slug,name=name,color=color,shape=shape) for slug,name,color,shape in (
 ('lead_ball','Lead balls','#ccc6b1','ball'),
 ('pistol_45','.45 pistol cartridges','#ffc96b','bullet'),
 ('smg_9mm','9 mm SMG cartridges','#e2c277','short'),
 ('revolver','Revolver cartridges','#f2ac63','bullet'),
 ('shotgun','Shotgun shells','#ff873c','shell'),
 ('rifle','Rifle cartridges','#ffca7a','rifle'),
 ('heavy_rifle','Heavy rifle cartridges','#ffe3ae','rifle'),
 ('disc','Saw discs','#f1b858','disc'),
 ('rail','Conductive rail slugs','#45e4f2','rod'),
 ('rocket','Rocket rounds','#ff603b','rocket'),
 ('energy','Energy cells','#56b9ff','cell'),
 ('plasma','Plasma capacitors','#bf71ff','cell'),
 ('prism','Prismatic needles','#88eefa','crystal'),
 ('soul','Soul charges','#e771d4','soul'),
 ('swarm','Swarm capsules','#edce57','capsule'),
 ('seed','Briar seed pods','#a6d54e','seed'),
 ('tide','Tidal pearls','#56ddcd','pearl'),
 ('ember','Ember cores','#ff8e42','ember'),
 ('frost','Frost splinters','#a4eaff','crystal'),
)}

# construction: ammo, rounds/s, capacity, reload seconds, range metres,
# damage per projectile, projectiles per shot, cone degrees, visual speed m/s
_RULES={
 'flintlock':('lead_ball',.65,1,2.4,40,30,1,1,140),
 '1911':('pistol_45',4,7,1.5,55,16,1,.5,180),
 'duckfoot':('lead_ball',.55,4,3.1,28,12,4,7,130),
 'silenced':('pistol_45',3,10,1.6,60,14,1,.4,180),
 'wheellock':('lead_ball',.7,1,2.7,45,34,1,1,140),
 'derringer':('revolver',1.5,2,2.0,25,19,1,1.2,150),
 'blunderbuss':('shotgun',.6,1,3.0,22,6,10,9,130),
 'target':('revolver',2.3,6,2.1,75,27,1,.25,200),
 'snubnose':('revolver',3.5,6,1.8,30,19,1,1.7,160),
 'uzi':('smg_9mm',12,32,2.0,45,7,1,1.8,200),
 'hunting':('shotgun',1.1,2,2.4,35,6,8,4.2,170),
 'pump':('shotgun',1.4,6,3.0,40,5,9,3.8,170),
 '1911_long':('pistol_45',3.5,8,1.6,65,18,1,.3,190),
 'lever_rifle':('rifle',1.7,10,3.0,110,32,1,.25,240),
 'breakshot':('shotgun',1.2,2,2.2,42,6,7,3.2,180),
 'bolt':('heavy_rifle',.65,5,2.8,180,65,1,.1,340),
 'assault':('rifle',9,30,2.3,100,10,1,.8,250),
 'bullpup':('rifle',7,24,2.1,90,13,1,.7,250),
 'smg':('smg_9mm',14,28,1.8,35,6,1,2.2,180),
 'boxmag':('energy',2.8,10,2.0,75,25,1,.4,85),
 'disc':('disc',1.2,6,2.2,65,35,1,.3,40),
 'gatling':('rifle',18,80,4.0,85,7,1,2,220),
 'rail':('rail',.85,6,2.4,160,58,1,.1,600),
 'rocket':('rocket',.5,1,3.2,110,75,1,.1,38),
 'blaster':('energy',4.5,18,1.9,75,19,1,.5,90),
 'plasma':('plasma',5,24,2.6,65,21,1,.8,65),
 'prism':('prism',2.2,12,2.1,95,29,1,.2,130),
 'demon':('soul',2,9,2.0,65,30,1,.5,70),
 'hive':('swarm',1.7,8,2.6,48,4,7,3,45),
 'thorn':('seed',2.5,14,1.9,55,20,1,.7,60),
 'conch':('tide',1.8,8,2.1,60,29,1,.8,55),
 'dragon':('ember',1.5,6,2.5,45,32,1,1,60),
 'raven':('soul',2.8,12,2.0,80,23,1,.3,80),
 'frost':('frost',1.7,8,2.3,65,15,2,1.5,90),
 'squid':('tide',3.2,16,2.1,40,16,1,1.4,50),
 'phoenix':('ember',2.3,12,2.2,70,24,1,.5,100),
}
_STATUS={'demon':('lifesteal',.10,0),'hive':('poison',1.3,4),
 'thorn':('snare',1,.7),'conch':('weaken',.10,3),'dragon':('burn',2,3),
 'raven':('weaken',.15,3),'frost':('slow',.3,3),'squid':('attack_slow',.2,3),
 'phoenix':('heal',2,0)}

def profile(instance_id):
    variant=variant_for(instance_id);name,kind,*_=PISTOLS[variant]
    ammo,rof,capacity,reload_s,distance,damage,pellets,spread,speed=_RULES[kind]
    status=_STATUS.get(kind)
    return dict(variant=variant,name=name,construction=kind,ammo_id=AMMO[ammo]['id'],
        ammo_name=AMMO[ammo]['name'],color=AMMO[ammo]['color'],shape=AMMO[ammo]['shape'],
        rounds_per_s=rof,capacity=capacity,reload_s=reload_s,range_m=distance,
        damage_per_projectile=damage,projectiles=pellets,spread_deg=spread,speed_m_s=speed,
        rounds_per_shot=4 if kind=='duckfoot' else 2 if kind=='frost' else 1,
        automatic=kind in ('uzi','smg','assault','bullpup','gatling','plasma'),
        armor_penetration=.65 if kind in ('rail','bolt','prism') else 0,
        status_effects=[dict(kind=status[0],amount=status[1],duration_s=status[2])] if status else [],
        wielding_reference='2H' if kind in TWO_HANDED else '1H',weapon_subtype=SUBTYPES.get(kind,'pistol'))

def normalize_magazine(raw,spec):
    raw=raw if isinstance(raw,dict) else {}
    def number(key):
        try:value=float(raw.get(key,0))
        except (ValueError,TypeError,OverflowError):return 0
        return value if math.isfinite(value) else 0
    rounds=max(0,min(spec['capacity'],int(number('rounds'))))
    return dict(rounds=rounds,pending=max(0,min(spec['capacity']-rounds,int(number('pending')))),
        reload_until=max(0,number('reload_until')),next_fire=max(0,number('next_fire')),
        shots=max(0,min(1000000000,int(number('shots')))))

def settle(instance,now):
    spec=profile(instance['instance_id']);mag=normalize_magazine(instance.get('magazine'),spec)
    if mag['pending'] and now+1e-8>=mag['reload_until']:
        mag['rounds']+=mag['pending'];mag['pending']=0;mag['reload_until']=0
    instance['magazine']=mag
    return spec,mag

def projectile_offsets(spec,distance,seed):
    """Stable cone; central pellet gives a aimed shotgun a reliable core hit."""
    radius=math.tan(math.radians(spec['spread_deg']))*distance
    count=spec['projectiles'];phase=(int(seed)%997)*math.tau/997
    return [(0.,0.)]+[(math.cos(phase+i*2.399963)*radius*math.sqrt(i/max(1,count-1)),
                       math.sin(phase+i*2.399963)*radius*math.sqrt(i/max(1,count-1))) for i in range(1,count)]

def crafting_recipes():
    out={}
    for slug,ammo in AMMO.items():
        magical=ammo['shape'] in ('cell','crystal','soul','capsule','seed','pearl','ember')
        inputs={'material.resin':1,'material.runic_oil':1} if magical else {'material.iron_ingot':1,'material.flint':1}
        out['recipe.ammo_'+slug]=dict(id='recipe.ammo_'+slug,name='Craft '+ammo['name'],
            inputs=inputs,output={ammo['id']:6 if slug in ('rocket','disc') else 24},
            station_id='station.workbench',profession='SURVIVAL',difficulty=1,tags=['AMMUNITION','CRAFT'])
    return out
