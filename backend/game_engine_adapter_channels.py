"""Local channel membership, moderation and original message routing."""
import copy
import hashlib
import hmac
import secrets
from backend.game_engine_adapter_local_client import text, integer

ZONE_CHANNELS=('General','Trade','LocalDefense','LookingForGroup','GuildRecruitment')

def defaults():return dict(channels=[],channel_slots=[None]*10,guild_recruitment=0)

def password_record(password):
    if not isinstance(password,str) or len(password)>128:raise ValueError('CHANNEL_PASSWORD_INVALID')
    if not password:return None
    salt=secrets.token_hex(16)
    return dict(salt=salt,digest=hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=4096,r=8,p=1).hex())

def password_matches(password,record):
    if not isinstance(password,str) or len(password)>128:raise ValueError('CHANNEL_PASSWORD_INVALID')
    if not record:return True
    value=hashlib.scrypt(password.encode(),salt=bytes.fromhex(record['salt']),n=4096,r=8,p=1).hex()
    return hmac.compare_digest(value,record['digest'])

class ChannelsMixin:
    def _restore_channels_locked(self):
        for key,value in defaults().items():self._services.setdefault(key,copy.deepcopy(value))
        rows=self._services['channels'];slots=self._services['channel_slots']
        if not isinstance(rows,list) or len(rows)>32 or not isinstance(slots,list) or len(slots)!=10:raise ValueError('CHANNEL_CAPACITY')
        keys=set()
        for row in rows:
            name=text(row['name'],80);key=name.casefold()
            if key in keys:raise ValueError('CHANNEL_DUPLICATE')
            keys.add(key)
            for field in ('members','moderators','muted','banned'):
                values=row[field]
                if not isinstance(values,list) or len(values)>64 or len(set(values))!=len(values) or any(not isinstance(v,str) or not v or len(v)>64 for v in values):raise ValueError('CHANNEL_MEMBERS_INVALID')
            if not isinstance(row['owner'],str) or len(row['owner'])>64 or row['owner'] and row['owner'] not in row['members']:raise ValueError('CHANNEL_OWNER_INVALID')
            if any(type(row[k]) is not bool for k in ('builtin','moderated','announcements')):raise ValueError('CHANNEL_FLAGS_INVALID')
            record=row.get('password')
            if record:
                if not isinstance(record,dict) or len(record['salt'])!=32 or len(record['digest'])!=128:raise ValueError('CHANNEL_PASSWORD_RECORD_INVALID')
                bytes.fromhex(record['salt']);bytes.fromhex(record['digest'])
        joined=[v for v in slots if v is not None]
        if len(set(joined))!=len(joined) or any(not isinstance(v,str) or v not in keys for v in joined):raise ValueError('CHANNEL_SLOTS_INVALID')
        if any('player' not in r['members'] for r in rows if r['name'].casefold() in joined):raise ValueError('CHANNEL_MEMBERSHIP_INVALID')
        integer(self._services['guild_recruitment'],0,1)

    def _channel_name_locked(self,value):
        name=text(value,80)
        if name.isdecimal():
            index=integer(int(name),1,10);key=self._services['channel_slots'][index-1]
            row=next((r for r in self._services['channels'] if r['name'].casefold()==key),None)
            if not row:raise ValueError('CHANNEL_NOT_JOINED')
            return row['name']
        for builtin in ZONE_CHANNELS:
            if name.casefold() in (builtin.casefold(),(builtin+' - GG Island').casefold()):return builtin+' - GG Island'
        return name

    def _channel_row_locked(self,value,joined=True):
        name=self._channel_name_locked(value)
        row=next((r for r in self._services['channels'] if r['name'].casefold()==name.casefold()),None)
        if not row or joined and 'player' not in row['members']:raise ValueError('CHANNEL_NOT_JOINED')
        return row

    def _channel_notice_locked(self,row,notice):
        slot=next((i+1 for i,v in enumerate(self._services['channel_slots']) if v==row['name'].casefold()),0)
        own_name=getattr(self,'_local_character_name','Gold Goblin')
        return [{'event':'CHAT_MSG_CHANNEL_NOTICE','args':[notice,own_name,'GG',row['name'],own_name,'',0,slot,row['name'],slot]}]

    def _channel_command_locked(self,request):
        op=request['op'];rows=self._services['channels'];slots=self._services['channel_slots']
        if op=='ChannelRecruitment':
            value=integer(request.get('value'),0,1);self._services['guild_recruitment']=value
            if value and not self._services['guild']:return self._channel_command_locked(dict(op='ChannelJoin',name='GuildRecruitment',password='',auto=True))
            return []
        if op=='ChannelListAll':return [{'event':'CHAT_MSG_SYSTEM','args':[', '.join(r['name'] for r in rows if 'player' in r['members'])]}]
        name=self._channel_name_locked(request.get('name'));key=name.casefold()
        row=next((r for r in rows if r['name'].casefold()==key),None)
        if op=='ChannelJoin':
            if row and 'player' in row['members']:return []
            shared_reserved=getattr(self,'_shared_channel_reserved_slots_locked',lambda:set())()
            free_slot=next((i for i,value in enumerate(slots) if value is None and i+1 not in shared_reserved),None)
            if free_slot is None:raise ValueError('CHANNEL_JOIN_CAPACITY')
            if row:
                if 'player' in row['banned']:raise ValueError('CHANNEL_BANNED')
                if not password_matches(request.get('password',''),row['password']):raise ValueError('CHANNEL_PASSWORD_INVALID')
                if len(row['members'])>=64:raise ValueError('CHANNEL_MEMBER_CAPACITY')
            else:
                if len(rows)>=32:raise ValueError('CHANNEL_CAPACITY')
                builtin=any(name==v+' - GG Island' for v in ZONE_CHANNELS)
                row=dict(name=name,owner='' if builtin else 'player',members=[],moderators=[],muted=[],banned=[],builtin=builtin,moderated=False,announcements=True,
                    password=None if builtin else password_record(request.get('password','')))
                if builtin:row['members']=[p['id'] for p in self._local_people_locked() if p['id']!='player'][:63]
                rows.append(row)
            row['members'].append('player');slots[free_slot]=key
            if not row['builtin'] and not row['owner']:row['owner']='player'
            if name=='GuildRecruitment - GG Island' and not request.get('auto'):self._services['guild_recruitment']=0
            return self._channel_notice_locked(row,'YOU_JOINED')
        row=self._channel_row_locked(name)
        if op=='ChannelMessage':return self._channel_chat_locked(dict(target=name),text(request.get('text'),255))
        if op=='ChannelLeave':
            notice=self._channel_notice_locked(row,'YOU_LEFT');row['members'].remove('player');slots[slots.index(key)]=None
            for field in ('moderators','muted'):
                if 'player' in row[field]:row[field].remove('player')
            if row['owner']=='player':row['owner']=next(iter(row['members']),'')
            if name=='GuildRecruitment - GG Island':self._services['guild_recruitment']=0
            return notice
        if op in ('ChannelList','ChannelDisplayOwner'):
            names=[self._service_unit_locked(i)['name'] for i in row['members']]
            message=', '.join(names) if op=='ChannelList' else (self._service_unit_locked(row['owner'])['name'] if row['owner'] else 'Local world')
            return [{'event':'CHAT_MSG_CHANNEL_LIST','args':[message,'','GG',row['name'],'','',0,slots.index(key)+1,row['name'],slots.index(key)+1]}]
        owner=row['owner']=='player';moderator=owner or 'player' in row['moderators']
        if row['builtin'] or not moderator:raise ValueError('CHANNEL_MODERATOR_REQUIRED')
        if op in ('ChannelSetOwner','ChannelSetPassword','ChannelModerator','ChannelUnmoderator') and not owner:raise ValueError('CHANNEL_OWNER_REQUIRED')
        if op=='ChannelSetPassword':row['password']=password_record(request.get('password',''));return []
        if op in ('ChannelModerate','ChannelToggleAnnouncements'):
            flag='moderated' if op=='ChannelModerate' else 'announcements';row[flag]=not row[flag];return []
        target=self._service_person_locked(request.get('player',''))
        if op=='ChannelInvite':
            if target in row['banned']:raise ValueError('CHANNEL_BANNED')
            if target not in row['members']:
                if len(row['members'])>=64:raise ValueError('CHANNEL_MEMBER_CAPACITY')
                row['members'].append(target)
        elif op=='ChannelUnban':
            if target in row['banned']:row['banned'].remove(target)
        else:
            if target not in row['members']:raise ValueError('CHANNEL_MEMBER_REQUIRED')
            if target==row['owner'] and op!='ChannelSetOwner':raise ValueError('CHANNEL_OWNER_PROTECTED')
            if op=='ChannelSetOwner':row['owner']=target
            elif op in ('ChannelKick','ChannelBan'):
                if target=='player':raise ValueError('CHANNEL_USE_LEAVE')
                row['members'].remove(target)
                for field in ('moderators','muted'):
                    if target in row[field]:row[field].remove(target)
                if op=='ChannelBan' and target not in row['banned']:row['banned'].append(target)
            elif op in ('ChannelModerator','ChannelUnmoderator','ChannelMute','ChannelUnmute'):
                field='moderators' if 'moderator' in op.lower() else 'muted';values=row[field]
                if op in ('ChannelUnmoderator','ChannelUnmute'):
                    if target in values:values.remove(target)
                elif target not in values:values.append(target)
            else:raise ValueError('CHANNEL_COMMAND_UNKNOWN')
        return self._channel_notice_locked(row,'OWNER_CHANGED' if op=='ChannelSetOwner' else 'INVITE' if op=='ChannelInvite' else 'MODE_CHANGE')

    def _channel_chat_locked(self,row,message):
        channel=self._channel_row_locked(row.get('target'));slot=self._services['channel_slots'].index(channel['name'].casefold())+1
        if 'player' in channel['muted'] or channel['moderated'] and channel['owner']!='player' and 'player' not in channel['moderators']:raise ValueError('CHANNEL_MUTED')
        recipients=','.join(i for i in channel['members'] if i!='player')
        own_name=getattr(self,'_local_character_name','Gold Goblin')
        self._append_event_locked('CHAT',own_name+': '+message,actor_id='player',target_id=recipients,payload={'channel':channel['name']})
        return [{'event':'CHAT_MSG_CHANNEL','args':[message,own_name,'GG',channel['name'],own_name,'',0,slot,channel['name'],slot]}]

    def _channels_view_locked(self):
        return dict(slots=[next((r['name'] for r in self._services['channels'] if r['name'].casefold()==key),None) if key else None for key in self._services['channel_slots']],
            recruitment=self._services['guild_recruitment'],rows=[{k:copy.deepcopy(v) for k,v in r.items() if k!='password'} for r in self._services['channels'] if 'player' in r['members']])
