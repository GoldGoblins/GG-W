"""Original gossip/quest verbs over exact, reachable GG authored content."""
from collections.abc import Mapping
from backend.game_engine_adapter_gameplay import QUALITY

class QuestViews:
    def __init__(self,identity):
        self.identity=identity;self.npc='';self.options={};self.rows={};self.active=[];self.available=[];self.log={};self.panel={}
    def update(self,snapshot):
        self.npc='';self.options={};self.rows={};self.active=[];self.available=[];self.log={};self.panel={}
        quests=snapshot.get('quests',{});dialogue=snapshot.get('dialogue',{});panel=snapshot.get('quest_dialog',{})
        active={row['id']:row for row in quests.get('active',[])[:20] if isinstance(row,Mapping) and row.get('id')}
        self.log={self.identity(key):key for key in active}
        catalog={row['id']:row for row in quests.get('catalog',[])[:32] if isinstance(row,Mapping) and row.get('id')}
        result={'gossip':{'open':False},'quest_dialog':{'open':False}}
        if not dialogue.get('open') or not dialogue.get('accessible'):return result
        self.npc=str(dialogue.get('active',{}).get('npc_id',''))
        if not self.npc:return result
        options=[]
        for index,row in enumerate(dialogue.get('node',{}).get('choices',[])[:32],1):
            ref=row.get('id');label=row.get('text') or row.get('label') or ref
            if not isinstance(ref,str) or not ref:continue
            self.options[index]=ref;options.append({'index':index,'label':str(label)[:512],'icon_type':'gossip'})
        rows=[]
        for key,row in catalog.items():
            if row.get('giver_id')!=self.npc:continue
            is_active=key in active
            if not is_active and key not in quests.get('available',[]):continue
            self.rows[len(rows)+1]=key
            (self.active if is_active else self.available).append(key)
            rows.append({'title':str(row.get('name',key))[:256],'level':int(row.get('level',1)),'active':is_active})
        result['gossip']={'open':not dialogue.get('gossip_hidden',False),'npc_id':self.npc,'greeting':str(dialogue.get('node',{}).get('text',''))[:4096],'quests':rows,'options':options}
        if panel.get('open') and panel.get('npc_id')==self.npc and panel.get('quest_id') in catalog:
            self.panel=dict(panel)
            row=catalog[panel['quest_id']];rewards=[]
            for item in panel.get('rewards',[])[:16]:
                ref=item['definition_id'];key=self.identity(ref);name=str(item.get('name',ref))[:128]
                rewards.append({'item_id':key,'name':name,'texture':item.get('icon'),'count':max(1,int(item.get('quantity',1))),'quality':QUALITY.get(item.get('rarity'),1),'usable':True,'link':'|Hitem:'+str(key)+':0:0:0|h['+name+']|h'})
            result['quest_dialog']={'open':True,'npc_id':self.npc,'quest_id':panel['quest_id'],'panel':panel['panel'],
                'title':str(row.get('name',''))[:256],'body':str(row.get('description',''))[:4096],
                'objectives':str(row.get('objective',{}).get('label',''))[:512],
                'reward_money':max(0,int(row.get('rewards',{}).get('gold',0)))*10000,
                'completable':panel.get('completable') is True,'rewards':rewards}
        return result
    def gossip(self,row):
        if type(row) is not int or row not in self.options or not self.npc:raise ValueError('GG gossip source is no longer available')
        return {'method':'gameEngineNpcTalk','args':[self.npc,self.options[row]]}
    def select(self,row,active=None):
        if active is None:key=self.rows.get(row) if type(row) is int else None
        else:
            rows=self.active if active else self.available
            key=rows[row-1] if type(row) is int and 1<=row<=len(rows) else None
        if not self.npc or not key:raise ValueError('GG quest source is no longer available')
        return {'method':'gameEngineQuestDialogSelect','args':[self.npc,key]}
    def action(self,action,choice=0):
        if not self.panel:raise ValueError('No GG quest panel is open')
        if type(choice) is not int or choice!=0:raise ValueError('GG quests have fixed authored rewards')
        return {'method':'gameEngineQuestDialogAction','args':[self.npc,self.panel['quest_id'],self.panel['panel'],str(action),choice]}
    def abandon(self,key):
        ref=self.log.get(key) if type(key) is int else None
        if not ref:raise ValueError('GG quest is no longer in the displayed log')
        return {'method':'gameEngineQuestAbandon','args':[ref]}
