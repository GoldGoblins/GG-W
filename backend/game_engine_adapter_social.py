"""Durable local guild administration and group loot over real GG objects."""
from __future__ import annotations
import copy
import hashlib
import math
from backend import game_engine_items as items
from backend.game_engine_adapter_local_client import integer, text
from backend.game_engine_adapter_loot_sources import validate_roll_source

RIGHT_BITS = (1, 2, 4, 8, 128, 256, 16, 32, 4096, 8192, 16384, 32768, 65536)
ALL_RIGHTS = sum(RIGHT_BITS)
QUALITY = {'POOR': 0, 'COMMON': 1, 'UNCOMMON': 2, 'RARE': 3, 'EPIC': 4, 'LEGENDARY': 5}

def event(name, *args):
    return [{'event': name, 'args': list(args)}]

def defaults():
    return dict(guild={}, guild_invite=None, group_invite=None, loot_rolls=[], loot_turn=0, free_loot=[])

def guild_record(name, leader='player', members=()):
    roster={leader:dict(rank=0,note='',officer_note='')}
    roster.update({p:dict(rank=4,note='',officer_note='') for p in members if p!=leader})
    return dict(name=name,motd='',info='',selection=0,show_offline=False,sort='rank',descending=False,
        ranks=[dict(name=n,rights=r) for n,r in [('Guild Master',ALL_RIGHTS),('Officer',ALL_RIGHTS&~65536),
            ('Veteran',3),('Member',3),('Initiate',3)]],members=roster)

def bounded_string(value, limit):
    if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 for c in value):
        raise ValueError('GUILD_TEXT_INVALID')
    return value


class SocialServicesMixin:
    def _restore_social_locked(self):
        for key, value in defaults().items():
            self._services.setdefault(key, copy.deepcopy(value))
        guild = self._services['guild']
        if not isinstance(guild, dict):
            raise ValueError('GUILD_SAVE_INVALID')
        if guild:
            bounded_string(guild['name'], 48)
            if guild.get('id') is not None:integer(guild['id'],1,self._services['next_id']-1)
            if guild.get('emblem') is not None:
                from backend.game_engine_adapter_tabards import checked_design
                checked_design(guild['emblem'])
            if not 5 <= len(guild['ranks']) <= 10 or not 1 <= len(guild['members']) <= 64:
                raise ValueError('GUILD_SAVE_CAPACITY')
            for rank in guild['ranks']:
                text(rank['name'], 32);integer(rank['rights'], 0, ALL_RIGHTS)
            if any(type(member.get('rank')) is not int or not 0 <= member['rank'] < len(guild['ranks'])
                   for member in guild['members'].values()):
                raise ValueError('GUILD_SAVE_RANK')
            if sum(member['rank'] == 0 for member in guild['members'].values()) != 1:
                raise ValueError('GUILD_SAVE_LEADER')
        if not isinstance(self._services['loot_rolls'], list) or len(self._services['loot_rolls']) > 64:
            raise ValueError('LOOT_ROLL_SAVE_CAPACITY')
        for roll in self._services['loot_rolls']:
            validate_roll_source(roll)
            integer(roll['id'], 1, self._services['next_id'] - 1)
            if len(roll['eligible']) > 40 or len(set(roll['eligible'])) != len(roll['eligible']):
                raise ValueError('LOOT_ROLL_SAVE_ELIGIBILITY')
            if not math.isfinite(roll['expires']):raise ValueError('LOOT_ROLL_SAVE_CLOCK')
            if roll['method'] not in ('group','needbeforegreed','master') or not isinstance(roll['votes'],dict):
                raise ValueError('LOOT_ROLL_SAVE_POLICY')
            if any(v not in roll['eligible'] or type(vote) is not int or vote not in (0,1,2) for v,vote in roll['votes'].items()):
                raise ValueError('LOOT_ROLL_SAVE_VOTES')
            confirmation=roll.get('confirmation')
            if confirmation is not None:
                if (not isinstance(confirmation,dict) or set(confirmation)!=set(('vote','expires','item'))
                        or type(confirmation['vote']) is not int or confirmation['vote'] not in (1,2)
                        or type(confirmation['expires']) not in (int,float) or not math.isfinite(confirmation['expires'])
                        or not 0<=confirmation['expires']<=roll['expires'] or not isinstance(confirmation['item'],dict)):
                    raise ValueError('LOOT_CONFIRM_SAVE_INVALID')
        free=self._services['free_loot']
        if not isinstance(free,list) or len(free)>64 or any(not isinstance(v,str) or len(v)>96 for v in free):
            raise ValueError('LOOT_PASS_SAVE_CAPACITY')
        integer(self._services['loot_turn'],0,2**31-1)
        for kind in ('guild_invite','group_invite'):
            invite=self._services[kind]
            if invite is not None:
                if not isinstance(invite,dict) or not isinstance(invite.get('leader'),str) or len(invite['leader'])>64:
                    raise ValueError('INVITATION_SAVE_INVALID')
                if not isinstance(invite.get('expires'),(int,float)) or not math.isfinite(invite['expires']):
                    raise ValueError('INVITATION_SAVE_CLOCK')
                if kind=='guild_invite':text(invite.get('name'),48)

    def _guild_right_locked(self, bit):
        guild = self._services['guild'];own = guild.get('members', {}).get('player')
        if not own or not guild['ranks'][own['rank']]['rights'] & bit:
            raise ValueError('GUILD_PERMISSION_DENIED')
        return guild, own

    def _guild_command_locked(self, row):
        op = row['op'];guild = self._services['guild']
        if op=='GuildRequestInvite':
            if guild:raise ValueError('GUILD_ALREADY_MEMBER')
            identity=self._service_person_locked(row.get('target'),nearby=True)
            if identity=='player':raise ValueError('GUILD_OTHER_PERSON_REQUIRED')
            name=text(row.get('name'),48)
            self._services['guild_invite']=dict(name=name,leader=identity,expires=self._service_now_locked()+60)
            return event('GUILD_INVITE_REQUEST',self._service_unit_locked(identity)['name'],name)
        if op in ('GuildAccept','GuildDecline'):
            invite=self._services['guild_invite']
            if not invite or invite['expires']<=self._service_now_locked():raise ValueError('GUILD_NO_PENDING_INVITATION')
            if op=='GuildAccept':
                if guild:raise ValueError('GUILD_ALREADY_MEMBER')
                self._services['guild']=dict(name=invite['name'],motd='',info='',selection=0,show_offline=False,sort='rank',descending=False,
                    ranks=[dict(name=n,rights=r) for n,r in [('Guild Master',ALL_RIGHTS),('Officer',ALL_RIGHTS&~65536),('Veteran',3),('Member',3),('Initiate',3)]],
                    members={invite['leader']:dict(rank=0,note='',officer_note=''),'player':dict(rank=4,note='',officer_note='')})
            self._services['guild_invite']=None
            return event('GUILD_ROSTER_UPDATE')+event('PLAYER_GUILD_UPDATE','player')
        if op == 'GuildCreate':
            if guild:raise ValueError('GUILD_ALREADY_MEMBER')
            name = text(row.get('name'), 48)
            self._service_money_locked(delta=-10000)
            self._services['guild'] = guild_record(name)
            return event('PLAYER_GUILD_UPDATE', 'player') + event('GUILD_ROSTER_UPDATE')
        if not guild or 'player' not in guild['members']:raise ValueError('GUILD_MEMBERSHIP_REQUIRED')
        own = guild['members']['player'];members = guild['members'];ranks = guild['ranks']
        if op in ('GuildInvite', 'GuildUninvite', 'GuildPromote', 'GuildDemote', 'GuildLeader'):
            right = {'GuildInvite': 16, 'GuildUninvite': 32, 'GuildPromote': 128,
                     'GuildDemote': 256, 'GuildLeader': 65536}[op]
            self._guild_right_locked(right)
            identity = self._service_person_locked(row.get('target'))
            if op == 'GuildInvite':
                if identity in members:raise ValueError('GUILD_ALREADY_MEMBER')
                if len(members) >= 64:raise ValueError('GUILD_ROSTER_FULL')
                members[identity] = dict(rank=len(ranks)-1, note='', officer_note='')
            else:
                if identity not in members or identity == 'player':raise ValueError('GUILD_OTHER_MEMBER_REQUIRED')
                target = members[identity]
                if target['rank'] <= own['rank']:raise ValueError('GUILD_RANK_TOO_HIGH')
                if op == 'GuildUninvite':del members[identity]
                elif op == 'GuildPromote':
                    if target['rank'] - 1 <= own['rank']:raise ValueError('GUILD_CANNOT_PROMOTE_TO_OWN_RANK')
                    target['rank'] -= 1
                elif op == 'GuildDemote':
                    if target['rank'] == len(ranks)-1:raise ValueError('GUILD_LOWEST_RANK')
                    target['rank'] += 1
                else:
                    if own['rank'] != 0:raise ValueError('GUILD_MASTER_REQUIRED')
                    own['rank'] = 1;target['rank'] = 0
        elif op in ('GuildMotd', 'GuildInfoText'):
            self._guild_right_locked(4096 if op == 'GuildMotd' else 65536)
            guild['motd' if op == 'GuildMotd' else 'info'] = bounded_string(row.get('text'), 255 if op == 'GuildMotd' else 1024)
        elif op in ('GuildPublicNote', 'GuildOfficerNote'):
            self._guild_right_locked(8192 if op == 'GuildPublicNote' else 32768)
            target = row.get('target')
            if target not in members:raise ValueError('GUILD_MEMBER_CHANGED')
            members[target]['note' if op == 'GuildPublicNote' else 'officer_note'] = bounded_string(row.get('text'), 255)
        elif op in ('GuildSaveRank', 'GuildAddRank', 'GuildDelRank'):
            if own['rank'] != 0:raise ValueError('GUILD_MASTER_REQUIRED')
            if op == 'GuildSaveRank':
                index = integer(row.get('rank_index'), 0, len(ranks)-1)
                rights = integer(row.get('rights'), 0, 0xffffffff) & ALL_RIGHTS
                ranks[index] = dict(name=text(row.get('name'), 32), rights=ALL_RIGHTS if index == 0 else rights)
            elif op == 'GuildAddRank':
                if len(ranks) == 10:raise ValueError('GUILD_MAX_RANKS')
                ranks.append(dict(name=text(row.get('name'), 32), rights=3))
            else:
                if len(ranks) == 5:raise ValueError('GUILD_MIN_RANKS')
                if any(m['rank'] == len(ranks)-1 for m in members.values()):raise ValueError('GUILD_RANK_HAS_MEMBERS')
                ranks.pop()
        elif op == 'GuildSelect':guild['selection'] = integer(row.get('index'), 0, len(members))
        elif op == 'GuildShowOffline':
            if type(row.get('show')) is not bool:raise ValueError('GUILD_FLAG_INVALID')
            guild['show_offline'] = row['show']
        elif op == 'GuildSort':
            field = row.get('field')
            if field not in ('name', 'zone', 'level', 'class', 'rank', 'note', 'online'):raise ValueError('GUILD_SORT_INVALID')
            guild['descending'] = not guild['descending'] if guild['sort'] == field else False;guild['sort'] = field
        elif op in ('GuildDisband', 'GuildLeave'):
            if op == 'GuildDisband' and own['rank'] != 0:raise ValueError('GUILD_MASTER_REQUIRED')
            if op == 'GuildLeave' and own['rank'] == 0 and len(members) > 1:raise ValueError('GUILD_TRANSFER_LEADERSHIP_FIRST')
            self._services['guild'] = {}
        elif op == 'GuildInfo':
            return event('CHAT_MSG_SYSTEM', guild['name'] + ': ' + str(len(members)) + ' members. ' + guild['info'])
        elif op != 'GuildRoster':raise ValueError('GUILD_COMMAND_UNKNOWN')
        result = event('GUILD_ROSTER_UPDATE') + event('PLAYER_GUILD_UPDATE', 'player')
        if op == 'GuildMotd':result += event('GUILD_MOTD', guild['motd'])
        return result

    def _guild_view_locked(self):
        guild = copy.deepcopy(self._services['guild'])
        if not guild:return None
        rows = []
        own = guild['members'].get('player')
        rights = guild['ranks'][own['rank']]['rights'] if own else 0
        for identity, member in guild['members'].items():
            unit = self._service_unit_locked(identity);person = next((p for p in self._local_people_locked() if p['id'] == identity), {})
            rows.append(dict(member, id=identity, name=unit['name'], level=unit['level'], online=unit['online'],
                rank_name=guild['ranks'][member['rank']]['name'], class_name=person.get('class_name', ''), zone=person.get('zone', ''),
                officer_note=member['officer_note'] if rights & 16384 else ''))
        key = {'class': 'class_name', 'rank': 'rank'}.get(guild['sort'], guild['sort'])
        guild['roster'] = sorted(rows, key=lambda r: r[key].casefold() if isinstance(r[key], str) else r[key], reverse=guild['descending'])
        guild.update(own_rank=own['rank'] if own else 0, rights=rights, in_guild=own is not None)
        return guild

    def _group_invitation_locked(self,row):
        op=row['op'];group=self._services['group']
        if op=='GroupRequestInvite':
            if group['members']:raise ValueError('GROUP_ALREADY_MEMBER')
            identity=self._service_person_locked(row.get('target'),nearby=True)
            if identity=='player':raise ValueError('GROUP_OTHER_PERSON_REQUIRED')
            self._services['group_invite']=dict(leader=identity,expires=self._service_now_locked()+60)
            return event('PARTY_INVITE_REQUEST',self._service_unit_locked(identity)['name'])
        invite=self._services['group_invite']
        if not invite or invite['expires']<=self._service_now_locked():raise ValueError('GROUP_NO_PENDING_LOCAL_INVITE')
        if op=='GroupAccept':
            if group['members']:raise ValueError('GROUP_ALREADY_MEMBER')
            group['members']=[invite['leader']];group['leader']=invite['leader'];group['subgroups']={invite['leader']:1,'player':1}
        self._services['group_invite']=None
        return event('PARTY_MEMBERS_CHANGED')+event('PARTY_LEADER_CHANGED')

    def _group_loot_route_locked(self, instance, source):
        group = self._services['group']
        existing = next((r for r in self._services['loot_rolls'] if r['item'] == instance['instance_id']), None)
        if existing:raise ValueError('LOOT_AWAITING_GROUP_DISTRIBUTION')
        if not group['members'] or group['loot_method'] == 'freeforall':return None
        if instance['instance_id'] in self._services['free_loot']:
            self._award_group_item_locked(instance,source,'player')
            self._services['free_loot'].remove(instance['instance_id']);return []
        roster = ['player'] + [v for v in group['members'] if self._service_unit_locked(v)['online']]
        definition = items.definition(self._item_catalog, instance['definition_id'])
        quality = QUALITY.get(definition.get('rarity'), 1)
        method = group['loot_method']
        if method == 'roundrobin' or quality < group['threshold']:
            winner = roster[self._services['loot_turn'] % len(roster)];self._services['loot_turn'] += 1
            self._award_group_item_locked(instance, source, winner)
            return event('LOOT_SLOT_CLEARED', list(self._engine_loot['ids']).index(instance['instance_id'])+1)
        if len(self._services['loot_rolls']) >= 64:raise ValueError('LOOT_ROLL_CAPACITY')
        roll = dict(id=self._service_id_locked(), item=instance['instance_id'], source=source['instance_id'],
            method=method, master=group['master'], eligible=roster, votes={},
            expires=self._service_now_locked()+60, bind=definition.get('bonding')==1 or definition.get('bind_on_pickup', False))
        for identity in roster:
            if identity != 'player':roll['votes'][identity] = 2
        self._services['loot_rolls'].append(roll)
        return event('LOOT_MASTER_LIST') if method == 'master' else event('START_LOOT_ROLL', roll['id'], 60000)

    def _award_group_item_locked(self, instance, source, winner):
        if winner == 'player':
            ok, result = self._move_item_locked(instance, 'INVENTORY', owner_id=winner)
            if not ok:raise ValueError(result['error'])
            self._record_quest_event_locked(dict(kind='PICKUP', target_id=instance['instance_id'],
                definition_id=instance['definition_id'], rarity=instance.get('rarity','COMMON'), amount=instance.get('quantity',1)))
        else:
            person=self._individual_state['individuals'].get(winner)
            if not person or not self._npc_add_inventory_ref_locked(person,instance['definition_id']):
                raise ValueError('LOOT_RECIPIENT_INVENTORY_FULL')
            self._service_move_locked(instance, 'POCKET', winner)
        definition=items.definition(self._item_catalog,instance['definition_id']) or {}
        if definition.get('bonding')==1 or definition.get('bind_on_pickup'):
            instance['bound_to']=str(self._persistence_key) if winner=='player' else winner
        self._refresh_loot_container_locked(source)
        self._append_event_locked('GROUP_LOOT', self._service_unit_locked(winner)['name'], actor_id=winner,
            subject_id=instance['instance_id'], payload=dict(source=source['instance_id']))

    def _loot_roll_command_locked(self, row):
        roll = next((r for r in self._services['loot_rolls'] if r['id'] == row.get('id')), None)
        if not roll:raise ValueError('LOOT_ROLL_CHANGED_OR_CLOSED')
        instance = self._item_instances.get(roll['item']);source = self._item_instances.get(roll['source'])
        if not self._loot_roll_source_matches_locked(roll, instance, source):
            raise ValueError('LOOT_ITEM_CHANGED')
        if row['op'] == 'LootMasterGive':
            if roll['method'] != 'master' or roll['master'] != 'player':raise ValueError('LOOT_MASTER_REQUIRED')
            winner = row.get('target')
            if winner not in roll['eligible']:raise ValueError('LOOT_CANDIDATE_CHANGED')
            self._award_group_item_locked(instance, source, winner)
            self._services['loot_rolls'].remove(roll)
        elif row['op'] == 'LootRollCancelConfirm':
            roll.pop('confirmation',None);return []
        elif row['op'] in ('LootRollVote','LootRollConfirm'):
            vote = integer(row.get('vote'),0,2)
            if roll['method'] == 'master' or 'player' not in roll['eligible']:raise ValueError('LOOT_VOTE_NOT_ELIGIBLE')
            if 'player' in roll['votes']:raise ValueError('LOOT_ALREADY_VOTED')
            definition = items.definition(self._item_catalog,instance['definition_id'])
            if vote == 1 and roll['method'] == 'needbeforegreed' and self._progression.get('level',1) < definition.get('required_level',0):
                raise ValueError('LOOT_CANNOT_NEED_UNUSABLE_ITEM')
            if self._service_now_locked()>=roll['expires']:raise ValueError('LOOT_ROLL_CHANGED_OR_CLOSED')
            signature={key:instance.get(key) for key in ('instance_id','definition_id','quantity','location','container_id')}
            if roll['bind'] and vote:
                if row['op']=='LootRollConfirm':
                    roll['confirmation']=dict(vote=vote,expires=roll['expires'],item=signature)
                    return event('CONFIRM_LOOT_ROLL',roll['id'],vote)
                confirmation=roll.get('confirmation')
                if (not confirmation or confirmation['vote']!=vote or confirmation['item']!=signature
                        or confirmation['expires']<=self._service_now_locked()):
                    raise ValueError('LOOT_BIND_CONFIRMATION_REQUIRED')
            elif row['op']=='LootRollConfirm':raise ValueError('LOOT_BIND_CONFIRMATION_NOT_REQUIRED')
            roll.pop('confirmation',None)
            roll['votes']['player'] = vote
            self._finish_loot_roll_locked(roll)
        else:raise ValueError('LOOT_COMMAND_UNKNOWN')
        return event('CANCEL_LOOT_ROLL', roll['id']) if roll not in self._services['loot_rolls'] else []

    def _finish_loot_roll_locked(self, roll):
        if roll['method'] == 'master' or len(roll['votes']) < len(roll['eligible']):return
        instance = self._item_instances.get(roll['item']);source = self._item_instances.get(roll['source'])
        if not self._loot_roll_source_matches_locked(roll, instance, source):raise ValueError('LOOT_ITEM_CHANGED')
        tier = [v for v in roll['eligible'] if roll['votes'].get(v) == 1]
        if not tier:tier = [v for v in roll['eligible'] if roll['votes'].get(v) == 2]
        if tier:
            def score(identity):
                digest = hashlib.sha256(f"{roll['id']}:{roll['item']}:{identity}".encode()).digest()
                return int.from_bytes(digest[:4], 'little') % 100 + 1
            winner = max(tier, key=lambda v:(score(v),v))
            self._award_group_item_locked(instance, source, winner)
        else:
            if len(self._services['free_loot'])>=64:raise ValueError('LOOT_PASS_CAPACITY')
            self._services['free_loot'].append(roll['item'])
        self._services['loot_rolls'].remove(roll)
        self._append_event_locked('LOOT_ROLL_FINISHED', str(roll['id']), actor_id='player')

    def _settle_group_loot_locked(self, now):
        for kind in ('guild_invite','group_invite'):
            invite=self._services[kind]
            if invite is not None and invite['expires']<=now:
                self._services[kind]=None;self._services['revision']+=1
        for roll in list(self._services['loot_rolls']):
            if roll['method'] != 'master' and roll['expires'] <= now:
                for identity in roll['eligible']:roll['votes'].setdefault(identity,0)
                self._finish_loot_roll_locked(roll);self._services['revision'] += 1

    def _loot_roll_view_locked(self):
        result = []
        for roll in self._services['loot_rolls']:
            row = dict(roll);row['attachment'] = self._service_item_view_locked(roll['item'])
            row['remaining_ms'] = max(0,int((roll['expires']-self._services['clock'])*1000))
            row['candidates'] = [self._service_unit_locked(v) for v in roll['eligible']]
            result.append(row)
        return result
