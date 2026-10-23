"""Local character preferences and original client intents over GG state.

Chat and addon delivery stay inside this local game session. World people are
the Who corpus; no online player, remote realm or external delivery is invented.
"""
from __future__ import annotations
import copy,math,random,re
from backend.game_engine_npc import MAX_NPCS

MAX_NAMES=50

def text(value,limit=128):
    if not isinstance(value,str) or not value.strip() or len(value)>limit or any(ord(c)<32 for c in value):raise ValueError('Ogiltig text.')
    return value.strip()

def integer(value,low,high):
    if type(value) is not int or not low<=value<=high:raise ValueError('Ogiltigt heltal.')
    return value

def defaults():
    return {'tutorials':[0]*32,'explored_zones':[0]*64,'action_bars':0,'pvp':False,'friends':[],'ignores':[],
        'selected_friend':0,'selected_ignore':0,'watched':None,'faction_flags':{},'level':1,'level_started':0.}

def restored(value):
    result=defaults()
    if not isinstance(value,dict):return result
    try:
        bank=value.get('tutorials',result['tutorials'])
        if not isinstance(bank,list) or len(bank)!=32:raise ValueError('tutorial bank')
        result['tutorials']=[integer(v,0,255) for v in bank]
        explored=value.get('explored_zones',[0]*64)
        if not isinstance(explored,list) or len(explored)!=64:raise ValueError('exploration bank')
        result['explored_zones']=[integer(v,0,2**32-1) for v in explored]
        result['action_bars']=integer(value.get('action_bars',0),0,255)
        if type(value.get('pvp',False)) is not bool:raise ValueError('pvp')
        result['pvp']=value.get('pvp',False)
        for key in ('friends','ignores'):
            names=value.get(key,[])
            if not isinstance(names,list) or len(names)>MAX_NAMES:raise ValueError('name capacity')
            result[key]=list(dict.fromkeys(text(v,48) for v in names))
        for key in ('selected_friend','selected_ignore'):result[key]=integer(value.get(key,0),0,MAX_NAMES)
        watched=value.get('watched')
        if watched is not None:watched=integer(watched,0,7)
        result['watched']=watched
        result['level']=integer(value.get('level',1),1,60)
        started=value.get('level_started',0.)
        if isinstance(started,bool) or not isinstance(started,(int,float)) or not math.isfinite(started) or not 0<=started<=1e9:raise ValueError('played time')
        result['level_started']=float(started)
        flags=value.get('faction_flags',{})
        if not isinstance(flags,dict) or len(flags)>8:raise ValueError('faction capacity')
        for key,flags in flags.items():
            integer(int(key),0,7)
            if not isinstance(flags,dict) or any(type(flags.get(k,False)) is not bool for k in ('at_war','inactive')):raise ValueError('faction flags')
            result['faction_flags'][str(int(key))]={'at_war':flags.get('at_war',False),'inactive':flags.get('inactive',False)}
    except (TypeError,ValueError,OverflowError):return defaults()
    return result

class LocalClientMixin:
    def _reset_local_client_locked(self):
        self._local_client=defaults();self._client_rng=random.Random(0x4747434c)
        self._who_filter='';self._who_to_ui=True

    def _local_people_locked(self):
        people=[]
        for index in self._npc_indices[:MAX_NPCS]:
            identity=self._npc_ids[index];person=self._individual_state.get('individuals',{}).get(identity,{})
            if not identity or not self._alive[index]:continue
            progression=person.get('progression',{})
            people.append(dict(name=person.get('name') or str(self._npc_archetype[index]).replace('_',' ').title(),
                level=int(progression.get('level',1)),class_name=str(progression.get('class_id','Local inhabitant')),
                race='GG',zone='GG Island',guild='',id=identity))
        people.insert(0,dict(name=getattr(self,'_local_character_name','Gold Goblin'),level=int(self._progression.get('level',1)),
            class_name=str(self._progression.get('class_id','')),race=str(self._progression.get('race','GG')),zone='GG Island',guild='',id='player'))
        guild=getattr(self,'_services',{}).get('guild',{})
        for person in people:
            if person['id'] in guild.get('members',{}):person['guild']=guild['name']
        return people

    def _local_who_matches_locked(self,people):
        # Original ui_social/query.rs quote/token conventions, using the
        # actual GG class/race/zone names in this local world's corpus.
        tokens=[];current='';quoted=False
        for c in self._who_filter:
            if c=='"':quoted=not quoted
            elif c.isspace() and not quoted:
                if current:tokens.append(current);current=''
            else:current+=c
        if current:tokens.append(current)
        terms=[];groups={};low,high=1,100
        fields={'n':'name','g':'guild','z':'zone','c':'class_name','r':'race'}
        for token in tokens:
            if len(token)>=2 and token[0].lower() in fields and token[1]=='-':
                tag=token[0].lower();value=token[2:].casefold()
                if tag in ('n','g'):groups[tag]=[value]
                else:groups.setdefault(tag,[]).append(value)
            elif re.fullmatch(r'[0-9]+(?:-[0-9]+)?',token):
                values=[int(n) for n in token.split('-')];low=max(1,min(100,values[0]));high=max(low,min(100,values[-1]))
            else:terms.append(token.casefold())
        return [p for p in people if low<=p['level']<=high and all(any(v in str(p[fields[k]]).casefold() for v in vs) for k,vs in groups.items())
            and all(any(v in str(p[k]).casefold() for k in ('name','guild','zone')) for v in terms)]

    def _local_client_view_locked(self):
        level=int(self._progression.get('level',1))
        if level!=self._local_client['level']:self._local_client.update(level=level,level_started=self._sim_time)
        result=copy.deepcopy(self._local_client)
        people=self._local_people_locked();who=self._local_who_matches_locked(people)
        result['who']=who[:49];result['who_total']=len(who)
        friends={name.casefold() for name in result['friends']};result['friend_people']=[p for p in people if p['name'].casefold() in friends][:50]
        from backend.game_engine_factions import FACTIONS
        result['factions']=[dict(id=key,name=value['name'],description=value['description'],standing=int(self._faction_state.get('player',{}).get(key,0))) for key,value in FACTIONS.items()]
        result['played_total']=max(0,int(self._sim_time));result['played_level']=max(0,int(self._sim_time-self._local_client['level_started']))
        return result

    def _local_client_command_locked(self,row):
        shared=getattr(self,'_shared_chat_command_locked',None)
        if shared is not None:
            result=shared(row)
            if result is not None:return result
        op=row.get('op');state=self._local_client
        if op=='ExploreArea':
            from backend.game_engine_adapter_navigation import explore_area
            return explore_area(self,row)
        event=lambda name,*args:[{'event':name,'args':list(args)}]
        if op=='TutorialFlag':
            index=integer(row.get('index'),0,49);state['tutorials'][index//8]|=1<<(index%8)
        elif op=='TutorialOverflow':raise ValueError('För många tutorialkommandon; inga tutorialflaggor ändrades.')
        elif op in ('TutorialClear','TutorialReset'):state['tutorials']=[255 if op=='TutorialClear' else 0]*32
        elif op=='ActionBars':state['action_bars']=integer(row.get('value'),0,255)
        elif op=='Pvp':state['pvp']=not state['pvp'];return event('UNIT_FLAGS','player')
        elif op=='Played':
            times=self._local_client_view_locked();return event('TIME_PLAYED_MSG',times['played_total'],times['played_level'])
        elif op=='Roll':
            low=integer(row.get('low'),0,1000000);high=integer(row.get('high'),low,1000000)
            value=self._client_rng.randint(low,high);name=getattr(self,'_local_character_name','Gold Goblin')
            self._append_event_locked('CHAT',f'{name} rolls {value} ({low}-{high}).',actor_id='player')
            return event('CHAT_MSG_SYSTEM',f'{name} rolls {value} ({low}-{high}).')
        elif op=='Chat':
            message=text(row.get('text'),255);kind=row.get('chat_type','SAY')
            if kind not in ('SAY','YELL','WHISPER','EMOTE','PARTY','RAID','GUILD','OFFICER','CHANNEL'):raise ValueError('Okänd chattkanal.')
            target=row.get('target');target_id=''
            if kind=='WHISPER':
                target=text(target,48);target_id=self._legacy_unit_locked(target,by_name=True)
                if not target_id:raise ValueError('Mottagaren finns inte i den lokala världen.')
            elif kind in ('PARTY','RAID'):
                group=self._services['group']
                if not group['members'] or kind=='RAID' and not group['raid']:raise ValueError('Ingen aktiv lokal grupp.')
                target_id=','.join(group['members'])
            elif kind in ('GUILD','OFFICER'):
                guild,own=self._guild_right_locked(8 if kind=='OFFICER' else 2)
                target_id=','.join(v for v,m in guild['members'].items()
                    if guild['ranks'][m['rank']]['rights'] & (4 if kind=='OFFICER' else 1))
            elif kind=='CHANNEL':return self._channel_chat_locked(row,message)
            name=getattr(self,'_local_character_name','Gold Goblin')
            self._append_event_locked('CHAT',f'{name}: {message}',actor_id='player',target_id=target_id,payload={'channel':kind,'message':message})
            return event('CHAT_MSG_'+('WHISPER_INFORM' if kind=='WHISPER' else kind),message,name,'GG','',name,'',0,0,'',0)
        elif op=='Addon':
            prefix=row.get('prefix');message=row.get('message')
            if not isinstance(prefix,str) or not isinstance(message,str) or len((prefix+'\t'+message).encode())>2047:raise ValueError('Ogiltigt tilläggsmeddelande.')
            distribution=row.get('distribution');group=self._services['group']
            if distribution not in ('PARTY','RAID') or not group['members'] or distribution=='RAID' and not group['raid']:
                raise ValueError('Tilläggsmeddelandet kräver en aktiv lokal grupp.')
            return event('CHAT_MSG_ADDON',prefix,message,distribution,getattr(self,'_local_character_name','Gold Goblin'))
        elif op=='Social':
            action=row.get('action')
            if action in ('AddFriend','RemoveFriendName','AddIgnore','DelIgnore','ToggleIgnore'):
                name=text(row.get('name'),48);key='friends' if action in ('AddFriend','RemoveFriendName') else 'ignores';rows=state[key]
                found=next((old for old in rows if old.casefold()==name.casefold()),None)
                remove=action in ('RemoveFriendName','DelIgnore') or (action=='ToggleIgnore' and found is not None)
                if remove:
                    if found is not None:rows.remove(found)
                elif found is None:
                    if len(rows)>=MAX_NAMES:raise ValueError('Listan är full.')
                    rows.append(name)
            elif action=='RemoveFriendIndex':
                index=integer(row.get('index'),1,len(state['friends']));state['friends'].pop(index-1)
            elif action in ('SelectFriend','SelectIgnore'):
                key='friends' if action=='SelectFriend' else 'ignores';state['selected_friend' if key=='friends' else 'selected_ignore']=integer(row.get('index'),0,len(state[key]))
            elif action=='Who':
                query=row.get('query')
                if not isinstance(query,str) or len(query)>255 or any(ord(c)<32 or ord(c)==127 for c in query):raise ValueError('Ogiltig sökfråga.')
                self._who_filter=query
                if not self._who_to_ui:return event('CHAT_MSG_SYSTEM',str(len(self._local_who_matches_locked(self._local_people_locked())))+' lokala invånare matchar sökningen.')
            elif action=='SetWhoToUi':
                value=row.get('value')
                if type(value) is not bool:raise ValueError('Ogiltigt sökläge.')
                self._who_to_ui=value;return []
            elif action=='RefreshFriends':pass
            else:raise ValueError('Den här grupptjänsten har ingen aktiv lokal session.')
            return event('WHO_LIST_UPDATE' if action=='Who' else 'FRIENDLIST_UPDATE')
        elif op=='Reputation':
            action=row.get('action');index=row.get('index')
            count=min(8,len(self._faction_state.get('player',{})))
            if action=='Watch':
                if index is not None:index=integer(index,0,count-1)
                state['watched']=index
            elif action in ('AtWar','Inactive'):
                index=integer(index,0,count-1);flag=row.get('value')
                if type(flag) is not bool:raise ValueError('Ogiltig fraktionsflagga.')
                state['faction_flags'].setdefault(str(index),{'at_war':False,'inactive':False})['at_war' if action=='AtWar' else 'inactive']=flag
            else:raise ValueError('Okänd fraktionsåtgärd.')
            return event('UPDATE_FACTION')
        elif op=='MinimapPing':
            point=row.get('position')
            if not isinstance(point,list) or len(point)!=2 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or abs(v)>1 for v in point):raise ValueError('Ogiltig kartposition.')
            return event('MINIMAP_PING','player',*point)
        else:raise ValueError('Okänt lokalt klientkommando.')
        return []
