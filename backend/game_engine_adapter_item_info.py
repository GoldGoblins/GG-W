"""Original tooltip descriptors for the actual GG item catalog.

Item level is not an equip requirement. GG traits without an original item-mod
type stay named in the description; no WoW server template or price is invented.
"""
from backend import game_engine_gear as gear
from backend import game_engine_assets as assets
from backend.game_engine_adapter_gameplay import identity, QUALITY

MODS={'health':1,'agility':3,'strength':4,'intellect':5,'spirit':6,'stamina':7}
INV={'HEAD':1,'NECK':2,'SHOULDERS':3,'SHIRT':4,'CHEST':5,'WAIST':6,'LEGS':7,'FEET':8,
     'WRISTS':9,'HANDS':10,'RING_1':11,'RING_2':11,'TRINKET_1':12,'TRINKET_2':12,'BACK':16,
     'MAIN_HAND':13,'OFF_HAND':23,'RANGED':15,'TABARD':19}
WEAPONS={'axe':(0,'Axe'),'mace':(4,'Mace'),'sword':(7,'Sword'),'knife':(15,'Dagger'),
         'staff':(10,'Staff'),'polearm':(6,'Polearm'),'fist':(13,'Fist Weapon'),'wand':(19,'Wand'),
         'bow':(2,'Bow'),'crossbow':(18,'Crossbow'),'pistol':(3,'Gun'),'rifle':(3,'Gun'),'shotgun':(3,'Gun'),'thrown':(16,'Thrown')}

def template_rows(catalog):
    definitions={ref:row for group in ('items','containers','insertables','materials') for ref,row in catalog.get(group,{}).items()}
    if len(definitions)>512:raise ValueError('ITEM_TEMPLATE_CAPACITY')
    rows=[]
    for ref,definition in sorted(definitions.items()):
        spec=gear.gear_spec_for_definition(ref,catalog.get('gear',{})) or {};stats=spec.get('base_stats',{})
        kind=definition.get('kind','ITEM');slot=definition.get('equip_slot','');inv=INV.get(slot,0)
        family=definition.get('weapon_subtype',definition.get('firearm_id','').split('.')[-1])
        if not family and kind=='WEAPON':family=spec.get('base_type','').lower().replace('_weapon','')
        cls=2 if kind=='WEAPON' else 4 if kind in ('ARMOR','ACCESSORY') or slot else 12 if kind=='QUEST' else 0 if kind=='CONSUMABLE' else 9 if kind=='SCROLL' else 7
        subclass,subname=WEAPONS.get(family,(0,'')) if cls==2 else (6,'Shield') if family=='shield' else (0,'')
        if cls==2 and definition.get('wielding')=='2H':inv=17
        if family=='shield':inv=14
        known=set(MODS)|{'armor','damage','durability'}
        extra=[f'{key.replace("_"," ").title()}: {value}' for key,value in stats.items() if key not in known]
        if stats.get('damage'):extra.insert(0,f"Damage bonus: {stats['damage']}")
        description=str(definition.get('description',''))
        if extra:description+='\n'+'\n'.join(extra)
        rows.append(dict(item_id=identity(ref),definition_id=ref,name=definition['name'],quality=QUALITY.get(definition.get('rarity'),1),
            item_type={2:'Weapon',4:'Armor',12:'Quest',0:'Consumable',9:'Recipe',7:'Trade Goods'}[cls],
            class_id=cls,subclass=subclass,subname=subname,inventory_type=inv,stackable=definition.get('stack_limit',1),
            stats=[[MODS[k],int(v)] for k,v in stats.items() if k in MODS],damage=0,
            armor=max(0,int(stats.get('armor',0))),max_durability=100 if kind in ('WEAPON','ARMOR') else 0,
            bonding=definition.get('bonding',0) if type(definition.get('bonding',0)) is int and 0<=definition.get('bonding',0)<=5 else 0,
            required_level=max(0,int(definition.get('required_level',0))),description=description[:2048],icon=definition.get('icon') or assets.inventory_icon(ref)))
    return rows

def enchant_rows(row):
    state=row.get('gear') or {};out=[]
    for i,enchant in enumerate(state.get('enchantments',[])[:7]):
        if not isinstance(enchant,dict):continue
        ref=enchant.get('enchant_id',enchant.get('id',''));definition=gear._enchant_metadata(ref)
        name=definition.get('name',enchant.get('name',ref))
        if name:out.append(dict(slot=i,negative=False,name=str(name)[:512],charges=0,remaining_ms=None))
    for modifier in state.get('modifiers',[]):
        if modifier.get('source')=='SOCKET':out.append(dict(slot=min(6,len(out)),negative=False,
            name=f"{modifier.get('stat','').replace('_',' ').title()}: {modifier.get('value',0)}",charges=0,remaining_ms=None))
    return out[:7]

class ItemInfoMixin:
    def _item_requirements_view_locked(self):
        # The GG-only catalog uses one unrestricted local class/race mask
        # category. These are requirement bits, not WoW Human/Warrior labels.
        return dict(class_id=1,race_id=1,skills=[[row['id'],row['level']] for row in self._skills_view_locked()['rows']])

    def _item_templates_view_locked(self):
        cached=getattr(self,'_engine_item_templates',None)
        if cached is None or cached[0] is not self._item_catalog:
            cached=(self._item_catalog,template_rows(self._item_catalog));self._engine_item_templates=cached
        members={ref:row['id'] for row in self._item_sets_locked() for ref in row['members']}
        for row in cached[1]:row['item_set']=members.get(row['definition_id'],0)
        return cached[1]

    def _item_info_command_locked(self,row):
        key=row.get('id')
        if type(key) is not int or not any(r['item_id']==key for r in self._item_templates_view_locked()):raise ValueError('ITEM_TEMPLATE_NOT_LOCAL')
        return [{'event':'GET_ITEM_INFO_RECEIVED','args':[key]}]
