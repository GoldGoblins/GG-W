"""Translate actual GG inventories, abilities and quests into GgEngine UI views."""
import zlib
QUALITY={'TRASH':0,'POOR':0,'COMMON':1,'UNCOMMON':2,'RARE':3,'EPIC':4,'LEGENDARY':5,'ARTIFACT':6,'MYTHIC':6}
EQUIPMENT_SLOTS={'HEAD':1,'NECK':2,'SHOULDERS':3,'SHIRT':4,'CHEST':5,'WAIST':6,'LEGS':7,'FEET':8,'WRISTS':9,'HANDS':10,'RING_1':11,'RING_2':12,'TRINKET_1':13,'TRINKET_2':14,'BACK':15,'MAIN_HAND':16,'OFF_HAND':17,'RANGED':18,'TABARD':19}
EQUIPMENT_NAMES={value:key for key,value in EQUIPMENT_SLOTS.items()}
def identity(ref):return (zlib.crc32(str(ref).encode())&0x7fffffff)|0x40000000

class GameplayViews:
    def __init__(self):
        self.items={};self.spells={};self.quests={};self.gold=0;self.copper=0;self.inventory_refs={};self.equipment_refs={};self.spell_refs={};self.identities={};self.action_refs={};self.macros={};self.progression={};self.talent_refs={}
        from backend.game_engine_adapter_bank import BankViews
        from backend.game_engine_adapter_merchant import MerchantViews
        self.bank=BankViews(self.identity);self.merchant=MerchantViews(self.identity)
        from backend.game_engine_adapter_quests import QuestViews
        self.quest=QuestViews(self.identity)
        from backend.game_engine_adapter_local_views import LocalViews
        self.local=LocalViews(self.identity)
        from backend.game_engine_adapter_service_views import ServiceViews
        self.services=ServiceViews(self.identity)
    def identity(self,ref):
        key=identity(ref);previous=self.identities.get(key)
        if previous is not None and previous!=ref:raise ValueError('GG gameplay identifier collision')
        self.identities[key]=ref
        return key
    def update(self,snapshot):
        if isinstance(snapshot.get('items'),dict):self.items=snapshot['items']
        if isinstance(snapshot.get('quests'),dict):self.quests=snapshot['quests']
        if isinstance(snapshot.get('progression'),dict):self.progression=snapshot['progression']
        if isinstance(snapshot.get('economy'),dict):
            wallet=snapshot['economy'].get('wallet',{});self.gold=max(0,int(wallet.get('gold',self.gold)));self.copper=max(0,min(9999,int(wallet.get('copper',0))))
        actions=snapshot.get('actions',{})
        if isinstance(actions.get('abilities'),list):self.spells={row['ref']:row for row in actions['abilities'][:128] if row.get('ref')}
        locked=set(snapshot.get('player',{}).get('client_controls',{}).get('services',{}).get('item_binding',{}).get('locked_items',[]))
        locked.update(snapshot.get('player',{}).get('client_controls',{}).get('services',{}).get('item_targeting',{}).get('locked_items',[]))
        wrap=snapshot.get('player',{}).get('client_controls',{}).get('services',{}).get('inventory_cursor',{}).get('wrap')
        if wrap:locked.add(wrap['paper'])
        inventory=[];self.inventory_refs={}
        for fallback,row in enumerate(self.items.get('inventory',[])[:64]):
            slot=int(row.get('slot_index',fallback));ref=row.get('definition_id','')
            if not 0<=slot<64 or not ref:continue
            item=self.identity(ref);quality=QUALITY.get(row.get('rarity'),1);name=str(row.get('name',ref));self.inventory_refs[slot+1]=(ref,row.get('instance_id',''))
            inventory.append({'slot':slot+1,'item_id':item,'name':name,'count':int(row.get('quantity',1)),'stack_limit':int(row.get('stack_limit',1)),'quality':quality,'kind':row.get('kind','ITEM'),'locked':row.get('instance_id') in locked,'link':'|Hitem:'+str(item)+':0:0:0|h['+name+']|h',**self.item_fields(row)})
        equipment=[];self.equipment_refs={}
        for row in self.items.get('equipment',[])[:24]:
            slot=EQUIPMENT_SLOTS.get(row.get('equipped_slot'));ref=row.get('definition_id')
            if slot is None or not ref:continue
            if slot in self.equipment_refs:raise ValueError('Duplicate GG equipment slot')
            self.equipment_refs[slot]=row.get('instance_id','');item=self.identity(ref);name=str(row.get('name',ref))
            equipment.append({'slot':slot,'item_id':item,'name':name,'count':int(row.get('quantity',1)),'quality':QUALITY.get(row.get('rarity'),1),'kind':row.get('kind','ITEM'),'locked':row.get('instance_id') in locked,'link':'|Hitem:'+str(item)+':0:0:0|h['+name+']|h',**self.item_fields(row)})
        self.spell_refs={self.identity(ref):ref for ref in self.spells};spells=[]
        if len(self.spell_refs)!=len(self.spells):raise ValueError('GG ability identifier collision')
        for ref,row in self.spells.items():
            action=next((s for s in actions.get('slots',[]) if s.get('ref')==ref),row)
            description=row.get('description') or ('Movement impulse: '+str(row['effect']['impulse']) if 'impulse' in row.get('effect',{}) else '')
            spells.append({'spell_id':self.identity(ref),'ref':ref,'name':str(row.get('name',ref)),'description':description,
                'resource_cost':row.get('resource_cost',0),'range_m':row.get('range_m',0),'cast_time_s':row.get('cast_time_s',0),
                **({'icon':row['icon']} if row.get('icon') else {}),
                'channel_time_s':row.get('channel_time_s',0),'current':row.get('current',False),
                'cooldown_s':float(action.get('cooldown_s',0)),'cooldown_duration_s':float(action.get('cooldown_duration_s',0))})
        quests=[]
        for row in self.quests.get('active',[])[:20]:
            progress=row.get('progress',{});objective=row.get('objective',{});cur=int(progress.get('current',0));req=int(progress.get('required',1))
            quests.append({'quest_id':self.identity(row.get('id','')),'title':str(row.get('name','')),'description':str(row.get('description','')),'objective':str(objective.get('label','')),'reward_copper':max(0,int(row.get('rewards',{}).get('gold',0)))*10000,'current':cur,'required':req,'complete':progress.get('status')=='READY','pushable':row.get('shareable',True) is True,'kind':'monster' if objective.get('kind')=='DEFEAT' else 'item' if objective.get('definition_id') else 'object'})
        from backend.game_engine_actions import COMMANDS
        self.action_refs={}
        def register(kind,key,ref):
            pair=(kind,key);previous=self.action_refs.get(pair)
            if previous is not None and previous!=ref:raise ValueError('GG packed action identifier collision')
            self.action_refs[pair]=ref;return key
        for ref in self.spells:register(0,self.identity(ref)&0xffffff,('ABILITY',ref))
        for row in inventory+equipment:
            ref=self.identities[row['item_id']]
            register(128,row['item_id']&0xffffff,('ITEM',ref))
        # The original kind byte reserves low ids 1..36 for real macros.
        command_ids={ref:0x800000|index for index,ref in enumerate(COMMANDS,1)}
        for ref,key in command_ids.items():register(64,key,('COMMAND',ref))
        for key in range(1,37):register(64,key,('MACRO',str(key)))
        slots=[]
        for row in actions.get('slots',[])[:120]:
            row=dict(row);kind=row.get('kind');ref=row.get('ref')
            if kind in ('ITEM','ABILITY'):
                tag=128 if kind=='ITEM' else 0;key=self.identity(ref)&0xffffff
                register(tag,key,(kind,ref));row.update(action_kind=tag,action_id=key)
            elif kind=='COMMAND' and ref in command_ids:row.update(action_kind=64,action_id=command_ids[ref])
            elif kind=='MACRO':
                macro=self.macros.get(int(ref)) if str(ref).isdigit() else None
                row.update(action_kind=64,action_id=int(ref),name=macro['name'] if macro else 'Missing macro',texture=macro.get('texture') if macro else None)
                spell=macro.get('bound_spell',0) if macro else -1
                ability=self.spells.get(self.spell_refs.get(spell,''))
                if ability:
                    for key in ('usable','cooldown_s','cooldown_duration_s','not_enough_resource','in_range','current'):
                        if key in ability:row[key]=ability[key]
                elif spell==-1 or spell>0:row.update(usable=False,reason='Unknown ability' if macro else 'Missing macro')
                else:row.update(usable=True,reason='')
            slots.append(row)
        points=self.progression.get('talent_points',0);ranks=self.progression.get('talents',{})
        if type(points) is not int or not 0<=points<2**31 or not isinstance(ranks,dict) or len(ranks)>32:raise ValueError('Invalid GG talent state')
        names={row['id']:str(row.get('name',row['id'])) for row in self.progression.get('talent_definitions',[]) if isinstance(row,dict) and isinstance(row.get('id'),str)}
        self.talent_refs={};talents=[]
        for i,(key,rank) in enumerate(ranks.items(),1):
            if not isinstance(key,str) or not key or len(key)>128 or type(rank) is not int or not 0<=rank<2**31:raise ValueError('Invalid GG talent rank')
            self.talent_refs[(1,i)]=key
            talents.append({'name':names.get(key,key.replace('_',' ').title()),'rank':rank,'max_rank':max(1,rank+points),
                'tier':(i-1)//4+1,'column':(i-1)%4+1,'learnable':points>0})
        return {'inventory':inventory,'equipment':equipment,'spells':spells,'quests':quests,'money_copper':self.gold*10000+self.copper,'actions':slots,'bank':self.bank.update(snapshot),'merchant':self.merchant.update(snapshot),'services':self.services.update(snapshot),'talents':{'points':points,'rows':talents},**self.quest.update(snapshot),**self.local.update(snapshot)}
    @staticmethod
    def item_fields(row):
        fields={'equip_slots':[EQUIPMENT_SLOTS[s] for s in row.get('equip_slots',[]) if s in EQUIPMENT_SLOTS],
                'already_bound':row.get('bound') is True,'instance_id':row.get('instance_id',''),
                'usable_on_actionbar':bool(row.get('scroll_enchant_id') or row.get('definition_id') in
                    ('item.gg_wrapping_paper','item.gg_wrapped_gift','item.gg_letter','item.guild_charter'))}
        if row.get('wrapped'):fields['flags']=8
        if row.get('icon'):fields['icon']=row['icon']
        if 'condition' in row:fields['durability']=[round(max(0,min(1,float(row['condition'])))*100),100]
        fields['enchants']=[]
        if (row.get('gear') or {}).get('enchantments'):
            from backend.game_engine_adapter_item_info import enchant_rows
            fields['enchants']=enchant_rows(row)
        return fields
