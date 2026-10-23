"""Shared local-character service adapter; central runtime opts into these hooks.

Route _shared_service_command_locked before the old local transaction wrapper;
overlay its completed view with _shared_services_view_locked.  NPC services keep
their existing physical registry.  Shared escrow is projected, never copied
into that registry until a durable collection transfers ownership.
"""
from __future__ import annotations
import copy
import time

from backend import game_engine_items as items
from backend.game_engine_adapter_gameplay import QUALITY,EQUIPMENT_SLOTS
from backend.game_engine_local_custody import RecoveryRequired,integer,digest
from backend import game_engine_local_petitions as petitions
from backend import game_engine_local_direct_trade as direct_trades
from backend import game_engine_local_channels as shared_channels
from backend.game_engine_local_groups_services import SharedLocalGroupLootMixin


def events(*names):
    return [{'event':name,'args':[]} for name in names]


class SharedLocalServicesMixin(SharedLocalGroupLootMixin, shared_channels.SharedLocalChannelsMixin, petitions.SharedLocalPetitionsMixin, direct_trades.SharedLocalDirectTradeMixin):
    def _shared_custody_locked(self,refresh=False):
        store=getattr(self,'_local_custody_store',None)
        character=getattr(self,'_local_character_id','')
        if not store or not character:return None
        cache=getattr(self,'_local_custody_cache',None)
        if refresh or not cache or cache.get('character')!=character:
            value=store.snapshot();value['character']=character;value['roster']=store.roster()
            if value.get('recovery',{}).get('status')=='COMMITTED':
                self._apply_local_custody_locked(value['characters'][character])
            self._local_custody_cache={key:value[key] for key in ('character','shared','roster')}
            self._local_custody_cache['petitions']=petitions.projections(value['characters'])
            value['petitions']=self._local_custody_cache['petitions']
            self._local_custody_cache['direct_trade_items']=direct_trades.projections(value['characters'],value['shared'])
            value['direct_trade_items']=self._local_custody_cache['direct_trade_items']
            if refresh:return value
        return self._local_custody_cache

    def _apply_local_custody_locked(self,envelope):
        """Merge only committed ownership/wallet facts; preserve live player systems."""
        payload=envelope['payload']
        self._item_instances={i['instance_id']:copy.deepcopy(i) for i in payload['item_instances']}
        self._inventory=copy.deepcopy(payload['inventory'])
        self._economy_state=copy.deepcopy(payload['economy_state'])
        revision=integer(envelope['revision'],0,2**63-1)
        self._persistence_revision=revision
        from backend.game_engine_local_characters import CharacterStore
        attached=getattr(self,'_state_store',None)
        if isinstance(attached,CharacterStore) and getattr(self,'_persistence_key',None)==self._local_character_id:
            attached._revision=max(attached.revision,revision)
        self._local_custody_cache=None
        self._local_custody_blocked=False
        self._local_custody_recovery_blocked=False
        self._local_custody_pending=None
        self._ui_snapshot_base=None;self._render_snapshot_cache=None;self._render_snapshot_signature=None

    def _shared_person_locked(self,value,snapshot):
        character=self._local_character_id
        if isinstance(value,str) and value.casefold()=='player':return character
        matches=[r['id'] for r in snapshot['roster'] if value==r['id'] or
                 isinstance(value,str) and value.casefold()==r['name'].casefold()]
        if len(matches)==1:return matches[0]
        if len(matches)>1:raise ValueError('SERVICE_PERSON_UNKNOWN_OR_AMBIGUOUS')
        return None

    def _shared_group_person_locked(self,value,snapshot,group):
        """Resolve displayed group tokens without touching the separate NPC roster."""
        character=self._local_character_id
        roster=[character]+[m for m in group['members'] if m!=character]
        if isinstance(value,str):
            token=value.casefold()
            if token.startswith('party') and token[5:].isdigit():
                others=[m for m in roster if m!=character and (not group['raid'] or group['subgroups'][m]==group['subgroups'][character])]
                index=int(token[5:]);return others[index-1] if 1<=index<=len(others) else None
            if token.startswith('raid') and token[4:].isdigit():
                index=int(token[4:]);return roster[index-1] if group['raid'] and 1<=index<=len(roster) else None
        return self._shared_person_locked(value,snapshot)

    def _shared_group_guids_locked(self,snapshot):
        identities=tuple(sorted(row['id'] for row in snapshot['roster']))
        cached=getattr(self,'_local_group_guid_cache',None)
        if cached and cached[0]==identities:return cached[1]
        assigned={};used=set()
        for member in identities:
            candidate=int(digest(member)[:8],16)&0x0fffffff
            while candidate in used:candidate=(candidate+1)&0x0fffffff
            used.add(candidate);assigned[member]=0x50000000|candidate
        self._local_group_guid_cache=(identities,assigned)
        return assigned

    def _shared_execute_locked(self,row,call):
        store=self._local_custody_store;character=self._local_character_id
        try:
            if getattr(self,'_local_custody_blocked',False):
                store.recover()
                fresh=store.snapshot()
                self._apply_local_custody_locked(fresh['characters'][character])
            snapshot=self._shared_custody_locked(refresh=True)
        except RecoveryRequired as error:self._fail_shared_recovery_locked(row,error)
        except OSError as error:raise ValueError('LOCAL_CUSTODY_SAVE_FAILED') from error
        sequence=row.get('custody_sequence',snapshot['shared']['sequences'].get(character,0)+1)
        integer(sequence,1,2**63-1)
        prior=snapshot['shared']['receipts'].get(character+':'+str(sequence))
        if not prior and sequence<=snapshot['shared']['sequences'].get(character,0):
            raise ValueError('LOCAL_CUSTODY_RECEIPT_EXPIRED')
        expected=prior['expected_revisions'].get(character) if prior else None
        if not prior:
            # Serialize the actual running character once before drafting the
            # transfer.  No full load/reinitialization occurs after collection.
            try:
                self.save_state(snapshot=False)
                snapshot=self._shared_custody_locked(refresh=True)
            except RecoveryRequired as error:self._fail_shared_recovery_locked(row,error)
            except OSError as error:raise ValueError('LOCAL_CUSTODY_SAVE_FAILED') from error
            expected=snapshot['characters'][character]['revision']
        try:
            result=call(store,character,sequence,expected)
        except RecoveryRequired:
            self._local_custody_blocked=True
            self._local_custody_recovery_blocked=True
            self._local_custody_pending=copy.deepcopy(row)
            try:
                store.recover()
                snapshot=store.snapshot()
                receipt=snapshot['shared']['receipts'].get(character+':'+str(sequence))
                if not receipt:raise ValueError('LOCAL_CUSTODY_RECEIPT_MISSING')
                result={'result':receipt['result'],'receipt':character+':'+str(sequence),'recovered':True}
            except Exception as error:
                self._fail_shared_recovery_locked(dict(row,custody_sequence=sequence),error)
        except OSError as error:raise ValueError('LOCAL_CUSTODY_SAVE_FAILED') from error
        try:snapshot=store.snapshot()
        except (OSError,ValueError) as error:
            # A successful commit followed by an unavailable final image is
            # recovery work even if the intent file has already been cleared.
            self._fail_shared_recovery_locked(dict(row,custody_sequence=sequence),error)
        # An ordinary replay changes no character image. Preserve legitimate
        # unsaved gameplay rather than loading an older disk checkpoint.
        # Mandatory recovery above already merged any committed final image.
        if not result.get('replayed'):self._apply_local_custody_locked(snapshot['characters'][character])
        self._local_custody_cache=dict(shared=snapshot['shared'],character=character,roster=store.roster())
        self._local_custody_cache['petitions']=petitions.projections(snapshot['characters'])
        self._local_custody_cache['direct_trade_items']=direct_trades.projections(snapshot['characters'],snapshot['shared'])
        return result

    def _fail_shared_recovery_locked(self,row,error):
        self._local_custody_blocked=True;self._local_custody_recovery_blocked=True
        self._local_custody_pending=copy.deepcopy(row)
        try:self.pause()
        except (OSError,ValueError):pass
        raise ValueError('LOCAL_CUSTODY_RECOVERY_REQUIRED') from error

    def _shared_service_command_locked(self,row):
        snapshot=self._shared_custody_locked()
        channel_result=self._shared_channel_command_locked(row,snapshot)
        if channel_result is not None:return channel_result
        trade_result=self._shared_direct_trade_command_locked(row,snapshot)
        if trade_result is not None:return trade_result
        if snapshot is None:return None
        petition_result=self._shared_petition_command_locked(row,snapshot)
        if petition_result is not None:return petition_result
        op=row.get('op','');shared=snapshot['shared'];character=self._local_character_id
        guild_id=next((k for k,g in shared['guilds'].items() if character in g['members']),None)
        group_id,group=self._local_custody_store._group_for(shared,character)
        prior=shared['receipts'].get(character+':'+str(row.get('custody_sequence','')))
        explicit='custody_sequence' in row
        old_sequence=type(row.get('custody_sequence')) is int and 1<=row['custody_sequence']<=shared['sequences'].get(character,0)
        group_replay=prior and prior['request'].get('op')=='GROUP_ACTION'
        if op.startswith('Group') and (explicit or group or op in ('GroupAccept','GroupDecline') and character in shared.get('group_invites',{}) or
                op in ('GroupInvite','GroupRequestInvite') and self._shared_person_locked(row.get('target'),snapshot) is not None):
            if op=='GroupMark' and not explicit and group and self._shared_group_person_locked(row.get('target','target'),snapshot,group) is None:
                # Real world marks belong to the existing physical NPC ledger.
                # Its save/rollback and person guards remain authoritative.
                return None
            if op=='GroupRequestInvite':raise ValueError('GROUP_RECIPIENT_CONSENT_REQUIRED')
            if op=='GroupRaidInfo':return events('UPDATE_INSTANCE_INFO')
            if op=='GroupReadyLine':
                from backend.game_engine_adapter_local_client import text
                return [{'event':'CHAT_MSG_SYSTEM','args':[text(row.get('text'),512)]}]
            if not (group_replay or old_sequence) and self._services['group']['members']:raise ValueError('GROUP_ALREADY_MEMBER')
            request={key:copy.deepcopy(value) for key,value in row.items() if key not in ('kind','session','custody_sequence')}
            if op=='GroupLoot':
                for field in ('master','threshold'):
                    if request.get(field) is None:request.pop(field,None)
            if op=='GroupKickRaid':
                roster=[character]+[m for m in group['members'] if m!=character]
                request['target']=roster[integer(request.pop('index',0),1,len(roster))-1];request['op']='GroupKick'
            for field in ('target','master','other_target'):
                if field in request:
                    request[field]=self._shared_group_person_locked(request[field],snapshot,group) if group else self._shared_person_locked(request[field],snapshot)
                    if request[field] is None:raise ValueError('GROUP_MEMBER_CHANGED')
            if op in ('GroupSubgroup','GroupSwap') and 'target' not in request:
                roster=[character]+[m for m in group['members'] if m!=character]
                request['target']=roster[integer(request.pop('index',0),1,len(roster))-1]
                if op=='GroupSwap':request['other_target']=roster[integer(request.pop('other',0),1,len(roster))-1]
            call=lambda store,owner,seq,revision:store.group_action(owner,seq,request)
            emitted=events('PARTY_MEMBERS_CHANGED','RAID_ROSTER_UPDATE','PARTY_LEADER_CHANGED')
            if op=='GroupReadyAnswer':emitted=[{'event':'READY_CHECK_CONFIRM','args':['player',row.get('ready')]}]
        elif op=='MailSend':
            recipient=self._shared_person_locked(row.get('target'),snapshot)
            if recipient is None or recipient==character:return None
            self._service_session_locked(row,'mail')
            call=lambda store,owner,seq,revision:store.send_mail(owner,seq,recipient,catalog=self._item_catalog,
                item_id=row.get('item',''),money=row.get('money',0),cod=row.get('cod',0),
                subject=row.get('subject',''),body=row.get('body',''),expected_revision=revision)
            emitted=events('MAIL_SEND_SUCCESS','MAIL_INBOX_UPDATE')
        elif op in ('MailRead','MailItem','MailMoney','MailDelete','MailReturn','MailText') and isinstance(row.get('id'),str):
            self._service_session_locked(row,'mail')
            if op in ('MailItem','MailMoney'):
                call=lambda store,owner,seq,revision:store.collect_mail(owner,seq,row['id'],collect='ITEM' if op=='MailItem' else 'MONEY',expected_revision=revision)
            elif op=='MailText':
                self._item_catalog.setdefault('items',{}).setdefault('item.gg_letter',dict(id='item.gg_letter',name='Letter',kind='ITEM',rarity='COMMON',stack_limit=1,tags=['NO_TRADE'],equip_slots=[]))
                call=lambda store,owner,seq,revision:store.save_mail_text(owner,seq,row['id'],catalog=self._item_catalog)
            else:
                action={'MailRead':'READ','MailDelete':'DELETE','MailReturn':'RETURN'}[op]
                call=lambda store,owner,seq,revision:store.mail_action(owner,seq,row['id'],action)
            emitted=events('MAIL_INBOX_UPDATE')
        elif op=='AuctionStart':
            self._service_session_locked(row,'auction')
            call=lambda store,owner,seq,revision:store.post_auction(owner,seq,row.get('item'),catalog=self._item_catalog,
                min_bid=row.get('min_bid'),buyout=row.get('buyout',0),duration=row.get('duration'))
            emitted=events('AUCTION_ITEM_LIST_UPDATE','AUCTION_OWNED_LIST_UPDATE')
        elif op in ('AuctionBid','AuctionCancel') and isinstance(row.get('id'),str):
            self._service_session_locked(row,'auction')
            if op=='AuctionBid':call=lambda store,owner,seq,revision:store.bid_auction(owner,seq,row['id'],row.get('amount'))
            else:call=lambda store,owner,seq,revision:store.finish_auction(owner,seq,row['id'],cancel=True)
            emitted=events('AUCTION_ITEM_LIST_UPDATE','AUCTION_OWNED_LIST_UPDATE','AUCTION_BIDDER_LIST_UPDATE','MAIL_INBOX_UPDATE')
        elif op=='GuildCreate' and not self._services['guild']:
            call=lambda store,owner,seq,revision:store.create_guild(owner,seq,row.get('name'))
            emitted=events('GUILD_ROSTER_UPDATE')+[{'event':'PLAYER_GUILD_UPDATE','args':['player']}]
        elif op=='GuildInvite' and guild_id:
            recipient=self._shared_person_locked(row.get('target'),snapshot)
            if recipient is None:raise ValueError('GUILD_LOCAL_CHARACTER_REQUIRED')
            call=lambda store,owner,seq,revision:store.invite_guild_member(owner,seq,guild_id,recipient)
            emitted=events('GUILD_ROSTER_UPDATE')
        elif op in ('GuildAccept','GuildDecline') and character in shared['guild_invites']:
            if op=='GuildAccept' and self._services['guild']:raise ValueError('GUILD_ALREADY_MEMBER')
            call=lambda store,owner,seq,revision:store.answer_guild_invite(owner,seq,op=='GuildAccept')
            emitted=events('GUILD_ROSTER_UPDATE')+[{'event':'PLAYER_GUILD_UPDATE','args':['player']}]
        elif op.startswith('Guild') and guild_id:
            if op=='GuildRoster':return events('GUILD_ROSTER_UPDATE')
            if op=='GuildInfo':return [{'event':'CHAT_MSG_SYSTEM','args':[shared['guilds'][guild_id]['name']+': '+shared['guilds'][guild_id]['info']]}]
            request=copy.deepcopy(row)
            request.pop('kind',None);request.pop('session',None);request.pop('custody_sequence',None)
            if 'target' in request:
                request['target']=self._shared_person_locked(request['target'],snapshot)
                if request['target'] is None:raise ValueError('GUILD_MEMBER_CHANGED')
            call=lambda store,owner,seq,revision:store.guild_action(owner,seq,guild_id,request)
            emitted=events('GUILD_ROSTER_UPDATE')+[{'event':'PLAYER_GUILD_UPDATE','args':['player']}]
        else:return None
        if not op.startswith('Group'):
            if self._player_defeated_locked():raise ValueError('PLAYER_DEFEATED')
            if self._services['taxi_flight']:raise ValueError('TAXI_IN_PROGRESS')
        outcome=self._shared_execute_locked(row,call)
        return outcome['result'].get('events',emitted)

    def _shared_chat_command_locked(self,row):
        op=row.get('op')
        if op not in ('Chat','Addon','SharedChatAck'):return None
        snapshot=self._shared_custody_locked()
        if snapshot is None:return None
        channel_result=self._shared_channel_chat_locked(row,snapshot)
        if channel_result is not None:return channel_result
        shared=snapshot['shared'];character=self._local_character_id
        if op=='SharedChatAck':
            ids=row.get('ids')
            if not isinstance(ids,list) or not 1<=len(ids)<=64 or any(not isinstance(k,str) for k in ids) or len(set(ids))!=len(ids):
                raise ValueError('LOCAL_CUSTODY_CHAT_ACK_INVALID')
            if any(len(k)!=37 or not k.startswith('chat-') or any(c not in '0123456789abcdef' for c in k[5:]) for k in ids):
                raise ValueError('LOCAL_CUSTODY_CHAT_ACK_INVALID')
            actual={m['id'] for m in shared.get('chat',{}).get(character,[])}
            prior=shared['receipts'].get(character+':'+str(row.get('custody_sequence','')))
            if not prior and not set(ids)&actual:return []
            if not prior and set(ids)-actual:raise ValueError('LOCAL_CUSTODY_CHAT_MESSAGE_CHANGED')
            self._shared_execute_locked(row,lambda store,owner,seq,revision:store.acknowledge_chat(owner,seq,ids))
            return []
        prior=shared['receipts'].get(character+':'+str(row.get('custody_sequence','')))
        explicit='custody_sequence' in row
        old_sequence=type(row.get('custody_sequence')) is int and 1<=row['custody_sequence']<=shared['sequences'].get(character,0)
        chat_replay=old_sequence
        kind='ADDON' if op=='Addon' else row.get('chat_type','SAY')
        if kind not in ('GUILD','OFFICER','WHISPER','PARTY','RAID','ADDON'):return None
        recipient=''
        if kind=='WHISPER':
            recipient=self._shared_person_locked(row.get('target'),snapshot)
            if recipient is None or recipient==character:
                if explicit:raise ValueError('LOCAL_CUSTODY_RECIPIENT_UNAVAILABLE')
                return None
        elif kind in ('PARTY','RAID','ADDON'):
            _,group=self._local_custody_store._group_for(shared,character)
            if group is None and not chat_replay:
                if explicit:raise ValueError('CHAT_GROUP_REQUIRED')
                return None
            if not chat_replay:
                if len(group['members'])<2:raise ValueError('CHAT_GROUP_REQUIRED')
                if (row.get('distribution') if kind=='ADDON' else kind)=='RAID' and not group['raid']:raise ValueError('GROUP_RAID_REQUIRED')
        else:
            guild=next((g for g in shared['guilds'].values() if character in g['members']),None)
            if guild is None and not chat_replay:
                if explicit:raise ValueError('GUILD_MEMBERSHIP_REQUIRED')
                return None
            if not chat_replay and not guild['ranks'][guild['members'][character]['rank']]['rights'] & (8 if kind=='OFFICER' else 2):
                raise ValueError('GUILD_PERMISSION_DENIED')
        from backend.game_engine_adapter_local_client import text
        message=row.get('message') if kind=='ADDON' else text(row.get('text'),255)
        outcome=self._shared_execute_locked(row,lambda store,owner,seq,revision:store.send_chat(owner,seq,kind,message,
            recipient=recipient,expected_revision=revision,prefix=row.get('prefix','') if kind=='ADDON' else '',
            distribution=row.get('distribution','') if kind=='ADDON' else ''))
        if outcome.get('replayed'):return []
        roster={r['id']:r['name'] for r in snapshot['roster']}
        speaker=roster[recipient] if kind=='WHISPER' else roster[character]
        if kind=='ADDON':return [{'event':'CHAT_MSG_ADDON','args':[row['prefix'],message,row['distribution'],speaker]}]
        self._append_event_locked('CHAT',roster[character]+': '+message,actor_id='player',
            target_id=','.join(outcome['result']['recipients']),payload={'channel':kind})
        return [{'event':'CHAT_MSG_'+('WHISPER_INFORM' if kind=='WHISPER' else kind),
                 'args':[message,speaker,'GG','',speaker,'',0,0,'',0]}]

    def _tick_shared_custody_locked(self):
        value=self._shared_custody_locked()
        if value is None or getattr(self,'_local_custody_blocked',False):return
        now=max(value['shared']['clock'],time.time());shared=value['shared']
        due=(any(a['expires']<=now for a in shared['auctions'].values()) or
             any(m['expires']<=now and not m['returned'] and not m['system'] for m in shared['mail'].values()) or
             any(i['expires']<=now for i in shared['guild_invites'].values()) or
             any(i['expires']<=now for i in shared.get('group_invites',{}).values()) or
             any(i['expires']<=now for i in shared.get('petition_offers',{}).values()) or
             any(i['expires']<=now for i in shared.get('direct_trades',{}).values()) or
             any(i['expires']<=now for i in shared.get('channel_invites',{}).values()) or
             any(g['ready'] and not g['ready']['finished'] and g['ready']['expires']<=now for g in shared.get('groups',{}).values()) or
             any(m.get('expires',float('inf'))<=now for inbox in shared.get('chat',{}).values() for m in inbox))
        if due and time.monotonic()>=getattr(self,'_local_custody_retry_at',0.):
            self._local_custody_retry_at=time.monotonic()+1.
            try:self._shared_execute_locked({'op':'SharedSettlement'},lambda store,owner,seq,revision:store.settle(owner,seq,now=now))
            except (ValueError,OSError):
                self._append_event_locked('LOCAL_SERVICE_RETRY','Shared custody settlement will retry after saving is available.',actor_id='player')

    def _shared_services_view_locked(self,value):
        snapshot=self._shared_custody_locked()
        if snapshot is None:return value
        value=copy.deepcopy(value);shared=snapshot['shared'];character=self._local_character_id
        roster={r['id']:r for r in snapshot['roster']}
        value['saved_recipients']=[dict(id=r['id'],name=r['name'],level=r.get('level',1)) for r in snapshot['roster'] if r['id']!=character]
        def name(key):return roster.get(key,{}).get('name',key)
        now=max(shared['clock'],self._services['clock'],time.time())
        for key,mail in shared['mail'].items():
            if mail['recipient']!=character:continue
            row=dict(mail,id=key,item=mail['asset'],sender_name='Auction House' if mail['system'] else name(mail['sender']),
                     sender='Auction House' if mail['system'] else mail['sender'],days_left=max(0,(mail['expires']-now)/86400))
            physical=shared['escrow'].get(mail['asset'])
            row['attachment']=items.instance_view(self._item_catalog,physical,sim_time=self._sim_time) if physical else None
            if row['invoice']:
                row['invoice']=dict(row['invoice'],player_name=name(row['invoice']['player_name']))
            value['mail']['rows'].append(row)
        value['mail']['unread']=sum(not m['read'] for m in value['mail']['rows'])
        live=[]
        for auction in self._services['auctions']:
            live.append(dict(auction,attachment=self._service_item_view_locked(auction['item']),owner_name=self._service_unit_locked(auction['owner'])['name']))
        for key,auction in shared['auctions'].items():
            physical=shared['escrow'][auction['asset']]
            live.append(dict(auction,id=key,item=auction['asset'],owner='player' if auction['owner']==character else auction['owner'],
                bidder='player' if auction['bidder']==character else name(auction['bidder']) if auction['bidder'] else '',
                attachment=items.instance_view(self._item_catalog,physical,sim_time=self._sim_time),owner_name=name(auction['owner'])))
        for a in live:
            remaining=a['expires']-now;a['time_left']=1 if remaining<1800 else 2 if remaining<7200 else 3 if remaining<43200 else 4
        lists=[]
        for index in range(3):
            selected=live if index==0 else [a for a in live if a['bidder' if index==1 else 'owner']=='player']
            if index==0:
                query=self._auction_query;needle=str(query.get('name','')).casefold()
                def match(a):
                    item=a['attachment'] or {};kind=item.get('kind','ITEM')
                    item_class=2 if kind=='WEAPON' else 4 if kind in ('ARMOR','ACCESSORY') else 0 if kind=='CONSUMABLE' else 7
                    return (needle in item.get('name','').casefold() and
                        (not query.get('min_level') or item.get('level',1)>=query['min_level']) and
                        (not query.get('max_level') or item.get('level',1)<=query['max_level']) and
                        (query.get('quality') is None or QUALITY.get(item.get('rarity'),1)>=query['quality']) and
                        (query.get('class') is None or query['class']==item_class) and query.get('sub_class') is None and
                        (query.get('inv_type') is None or query['inv_type'] in [EQUIPMENT_SLOTS.get(s) for s in item.get('equip_slots',[])]) and
                        (not query.get('usable_only') or item.get('level',1)<=self._progression.get('level',1)))
                selected=[a for a in selected if match(a)]
            for key,descending in reversed(self._auction_sorts[index]):
                def sort_key(a):
                    item=a['attachment'] or {}
                    return {'level':item.get('level',1),'quality':QUALITY.get(item.get('rarity'),1),'name':item.get('name','').casefold(),
                            'bid':a['bid'] or a['min_bid'],'buyout':a['buyout'],'duration':a['expires'],
                            'seller':a['owner_name'].casefold(),'status':int(a['bidder']=='player')}[key]
                selected=sorted(selected,key=sort_key,reverse=descending)
            offset=self._auction_pages[index]*50
            lists.append(dict(rows=selected[offset:offset+50],total=len(selected),sort=self._auction_sorts[index]))
        value['auction']['lists']=lists
        guild_id=next((k for k,g in shared['guilds'].items() if character in g['members']),None)
        if guild_id:
            guild=copy.deepcopy(shared['guilds'][guild_id]);own=guild['members'][character]
            rights=guild['ranks'][own['rank']]['rights'];rows=[]
            for member,record in guild['members'].items():
                profile=roster[member]
                rows.append(dict(record,id='player' if member==character else member,name=profile['name'],
                    level=self._progression.get('level',1) if member==character else profile.get('level',1),online=member==character,rank_name=guild['ranks'][record['rank']]['name'],
                    class_name=str(profile.get('selection',{}).get('class_id','')),zone='Local world' if member==character else '',
                    officer_note=record['officer_note'] if rights&16384 else ''))
            key={'class':'class_name','rank':'rank'}.get(guild['sort'],guild['sort'])
            guild['roster']=sorted(rows,key=lambda r:r[key].casefold() if isinstance(r[key],str) else r[key],reverse=guild['descending'])
            guild.update(id=int(digest(guild_id)[:8],16)%((2**31)-1)+1,shared_id=guild_id,own_rank=own['rank'],rights=rights,in_guild=True)
            value['guild']=guild
        invite=shared['guild_invites'].get(character)
        if invite and invite['expires']>now:
            guild=shared['guilds'][invite['guild']]
            value['guild_invite']=dict(invite,name=guild['name'])
            value['shared_pending_events']=[{'key':digest(invite),'event':'GUILD_INVITE_REQUEST','args':[name(invite['inviter']),guild['name']]}]
        else:value['shared_pending_events']=[]
        group_id,stored_group=self._local_custody_store._group_for(shared,character)
        if stored_group:
            group=copy.deepcopy(stored_group)
            physical_marks=copy.deepcopy(value['group'].get('marks',{}))
            physical_mark_guids=copy.deepcopy(value['group'].get('mark_guids',{}))
            alias=lambda member:'player' if member==character else member
            group['members']=[m for m in stored_group['members'] if m!=character]
            group['leader']=alias(group['leader']);group['master']=alias(group['master'])
            group['assistants']=[alias(m) for m in group['assistants']]
            group['subgroups']={alias(m):v for m,v in group['subgroups'].items()}
            group['marks']={**physical_marks,**{alias(m):v for m,v in group['marks'].items()}}
            ready=stored_group['ready'];group['ready']={alias(m):answer for m,answer in ready.get('answers',{}).items() if answer is not None}
            group['ready_check']=dict(id=ready['id'],initiator=alias(ready['initiator']),
                remaining=max(0,ready['expires']-now),finished=ready['finished'] or ready['expires']<=now) if ready else None
            group['shared_id']=group_id;group['roster']=[];guids=self._shared_group_guids_locked(snapshot)
            from backend.game_engine_adapter_identity import identity as character_identity
            for member in [character]+[m for m in stored_group['members'] if m!=character]:
                if member==character:
                    unit=self._service_unit_locked('player');unit['name']=name(member)
                else:
                    guid=guids[member]
                    unit=dict(id=member,guid=guid,name=name(member),level=roster[member].get('level',1),
                        online=False,is_connected=False,health=0,max_health=1,zone='')
                selected=roster[member].get('selection',{})
                labels=character_identity(dict(character_creation=dict(active=bool(selected),selection=selected),progression=self._progression if member==character else {}))
                cls=labels.get('class') or {}
                unit.update(class_name=cls.get('name',''),class_file=cls.get('file',''),raid_target=group['marks'].get(alias(member),0))
                group['roster'].append(unit)
            group['mark_guids']={**physical_mark_guids,**{str(unit['guid']):unit['raid_target'] for unit in group['roster'] if unit['raid_target']}}
            value['group']=group
            if ready:
                if group['ready_check']['finished']:
                    value['shared_pending_events'].append(dict(key=ready['id']+'-finished',event='READY_CHECK_FINISHED',args=[]))
                elif ready['answers'][character] is None:
                    value['shared_pending_events'].append(dict(key=ready['id'],event='READY_CHECK',args=[name(ready['initiator']),group['ready_check']['remaining']]))
        offer=shared.get('group_invites',{}).get(character)
        if offer and offer['expires']>now:
            value['group_invite']=dict(offer,leader_name=name(offer['leader']))
            value['shared_pending_events'].append(dict(key=digest(offer),event='PARTY_INVITE_REQUEST',args=[name(offer['inviter'])]))
        for message in shared.get('chat',{}).get(character,[])[:64]:
            if message.get('expires',float('inf'))<=now:continue
            speaker=name(message['sender'])
            if message['kind'] in ('CHANNEL','CHANNEL_NOTICE'):
                value['shared_pending_events'].append(dict(key=message['id'],ack_id=message['id'],
                    **shared_channels.message_event(message,speaker)))
                continue
            value['shared_pending_events'].append(dict(key=message['id'],ack_id=message['id'],
                event='CHAT_MSG_'+message['kind'],args=[message['prefix'],message['text'],message['distribution'],speaker] if message['kind']=='ADDON' else [message['text'],speaker,'GG','',speaker,'',0,0,'',0]))
        value['shared_custody']=dict(revision=shared['revision'],blocked=getattr(self,'_local_custody_blocked',False))
        return self._shared_channels_view_locked(self._shared_direct_trade_view_locked(value,snapshot),snapshot)
