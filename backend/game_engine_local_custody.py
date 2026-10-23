"""Recoverable local account custody for the local character runtime.

Character files keep their existing envelopes and appearances.  A durable,
bounded intent file commits final images before any character/shared-file
replacement.  Recovery is forward-only.  Callers MUST recover before loading
characters, checkpoint live state before submitting an operation, and merge
affected canonical assets after success or RecoveryRequired.  This is not a network
realm and does not include the independently stored live account stash.
"""
from __future__ import annotations
from backend.platform_files import secure_open, NOFOLLOW, CLOEXEC, NONBLOCK, sync_directory

import copy
from backend.platform_support import file_locks as fcntl
import hashlib
import json
import os
import stat
import tempfile
import threading
import time
import math
from contextlib import contextmanager
from pathlib import Path

from backend import game_engine_items as items, game_engine_trade as trade
from backend.game_engine_local_characters import MAX_BYTES, validate_payload
from backend.game_engine_adapter_social import guild_record,ALL_RIGHTS,SocialServicesMixin
from backend import game_engine_local_petitions as petitions
from backend import game_engine_local_direct_trade as direct_trades
from backend import game_engine_local_channels as shared_channels
from backend.game_engine_local_groups import LOOT_METHODS

SHARED_SCHEMA = 'gg.local-custody.v1'
JOURNAL_SCHEMA = 'gg.local-custody-intent.v1'
RETIREMENT_SCHEMA = 'gg.local-custody-retirement.v1'
MAX_SHARED_BYTES = 4 * 1024 * 1024
MAX_JOURNAL_BYTES = 48 * 1024 * 1024
MAX_RECEIPTS = 256
MAX_MAIL = 128
MAX_AUCTIONS = 64
MAX_GUILDS = 16
MAX_CHAT_INBOX = 64
MAX_GROUPS = 10
GROUP_INVITE_SECONDS = 60
GROUP_READY_SECONDS = 30
GROUP_CHAT_SECONDS = 30 * 86400
MAX_MONEY = 2_000_000_000 * 10000 + 9999
MAX_SEQUENCE = 2**63 - 1
MAX_CLOCK = 2**53 - 1
CONTEXT_FIELDS = frozenset(('instance_id', 'owner_id', 'location', 'container_id',
                            'equipped_slot', 'slot_index', 'custody_origin'))


class RecoveryRequired(OSError):
    """Intent is committed or its replacement occurred; ordinary rollback is unsafe."""
    committed = True

    def __init__(self, receipt, cause):
        self.receipt = receipt
        super().__init__('LOCAL_CUSTODY_RECOVERY_REQUIRED')
        self.__cause__ = cause


def encoded(value, limit):
    data = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                      separators=(',', ':')).encode('utf-8')
    if len(data) > limit:
        raise ValueError('LOCAL_CUSTODY_SIZE_LIMIT')
    return data


def digest(value):
    return hashlib.sha256(encoded(value, MAX_JOURNAL_BYTES)).hexdigest()


def identity(value):
    if not isinstance(value, str) or len(value) != 32 or any(c not in '0123456789abcdef' for c in value):
        raise ValueError('LOCAL_CUSTODY_CHARACTER_INVALID')
    return value


def integer(value, lower=0, upper=MAX_MONEY):
    if type(value) is not int or not lower <= value <= upper:
        raise ValueError('LOCAL_CUSTODY_INTEGER_INVALID')
    return value


def short_text(value, limit):
    if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 for c in value):
        raise ValueError('LOCAL_CUSTODY_TEXT_INVALID')
    return value


def addon_payload(prefix,message,distribution):
    """Original addon payloads are protocol bytes, not human chat text."""
    if not isinstance(prefix,str) or not isinstance(message,str) or distribution not in ('PARTY','RAID') or not (prefix or message):
        raise ValueError('LOCAL_CUSTODY_CHAT_INVALID')
    if len((prefix+'\t'+message).encode('utf-8'))>2047:raise ValueError('LOCAL_CUSTODY_CHAT_INVALID')


def origin(character, item):
    value = item.get('custody_origin', {'character': character, 'instance': item.get('instance_id')})
    if not isinstance(value, dict) or set(value) != {'character', 'instance'}:
        raise ValueError('LOCAL_CUSTODY_ORIGIN_INVALID')
    identity(value['character'])
    short_text(value['instance'], 64)
    if not value['instance']:
        raise ValueError('LOCAL_CUSTODY_ORIGIN_INVALID')
    return dict(value)


def asset_id(character, item):
    return 'custody-' + digest(origin(character, item))[:32]


def empty_shared():
    return dict(schema=SHARED_SCHEMA, revision=0, mail={}, auctions={}, guilds={},
                guild_invites={}, groups={}, group_invites={}, escrow={}, chat={}, money_sinks=0, sequences={}, receipts={},retired={}, clock=0.)


def clock(value):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= MAX_CLOCK:
        raise ValueError('LOCAL_CUSTODY_CLOCK_INVALID')
    return float(value)


class LocalCustodyStore(shared_channels.ChannelStoreMixin, petitions.PetitionStoreMixin, direct_trades.DirectTradeStoreMixin):
    """One account directory, its existing session lock, and bounded replay receipts.

    fault(stage, name) is an optional deterministic test hook.  Stages include
    before_write, file_synced, replaced, directory_synced, before_clear,
    journal_removed.  It is never serialized.
    """

    def __init__(self, root, *, session_lock=None, fault=None):
        self.root = Path(root).absolute()
        self.session_lock = session_lock
        self.fault = fault
        self._mutex = threading.RLock()

    def _fault(self, stage, name):
        if self.fault:
            self.fault(stage, name)

    def _path(self, name):
        # No user-provided path is ever interpreted as a journal destination.
        if name not in ('characters.json', '.session.lock', 'shared-custody.json',
                        'shared-custody.pending.json'):
            if not name.endswith('.json'):
                raise ValueError('LOCAL_CUSTODY_PATH_INVALID')
            identity(name[:-5])
        for path in (self.root, *self.root.parents):
            if path.is_symlink():
                raise ValueError('LOCAL_CUSTODY_SYMLINK')
        path = self.root / name
        if path.is_symlink():
            raise ValueError('LOCAL_CUSTODY_SYMLINK')
        return path

    @contextmanager
    def _locked(self):
        with self._mutex:
            self._path('.session.lock')
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            borrowed = self.session_lock is not None
            if borrowed:
                fd = self.session_lock if type(self.session_lock) is int else self.session_lock.fileno()
                actual = os.fstat(fd)
                try:
                    expected = os.stat(self._path('.session.lock'), follow_symlinks=False)
                except FileNotFoundError:
                    raise ValueError('LOCAL_CUSTODY_LOCK_INVALID') from None
                if not stat.S_ISREG(actual.st_mode) or (actual.st_dev, actual.st_ino) != (expected.st_dev, expected.st_ino):
                    raise ValueError('LOCAL_CUSTODY_LOCK_INVALID')
            else:
                fd = secure_open(self._path('.session.lock'), os.O_RDWR | os.O_CREAT | NOFOLLOW | CLOEXEC, 0o600)
            try:
                if not stat.S_ISREG(os.fstat(fd).st_mode):
                    raise ValueError('LOCAL_CUSTODY_LOCK_INVALID')
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise ValueError('LOCAL_CUSTODY_SESSION_BUSY') from None
                yield
            finally:
                if not borrowed:
                    os.close(fd)

    def _read(self, name, limit):
        path = self._path(name)
        try:
            fd = secure_open(path, os.O_RDONLY | NOFOLLOW | CLOEXEC)
        except FileNotFoundError:
            return None
        with os.fdopen(fd, 'rb') as file:
            if not stat.S_ISREG(os.fstat(file.fileno()).st_mode):
                raise ValueError('LOCAL_CUSTODY_FILE_INVALID')
            data = file.read(limit + 1)
        if len(data) > limit:
            raise ValueError('LOCAL_CUSTODY_SIZE_LIMIT')
        value = json.loads(data)
        encoded(value, limit)
        return value

    def _sync_directory(self):
        sync_directory(self.root)

    def _write(self, name, value, limit):
        data = encoded(value, limit)
        path = self._path(name)
        self._fault('before_write', name)
        fd, temporary = tempfile.mkstemp(prefix='.custody-', dir=self.root)
        try:
            with os.fdopen(fd, 'wb') as file:
                file.write(data)
                file.flush()
                os.fsync(file.fileno())
            self._fault('file_synced', name)
            self._path(name)
            os.replace(temporary, path)
            self._fault('replaced', name)
            self._sync_directory()
            self._fault('directory_synced', name)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _roster(self):
        registry = self._read('characters.json', MAX_BYTES)
        if not isinstance(registry, dict) or registry.get('schema') != 'gg.local-characters.v1':
            raise ValueError('LOCAL_CUSTODY_ROSTER_INVALID')
        rows = registry.get('characters')
        if not isinstance(rows, list) or not 0 <= len(rows) <= 10:
            raise ValueError('LOCAL_CUSTODY_ROSTER_INVALID')
        ids = [identity(row['id']) for row in rows]
        if len(set(ids)) != len(ids):
            raise ValueError('LOCAL_CUSTODY_ROSTER_INVALID')
        return ids

    def roster(self):
        with self._locked():
            self._recover_locked();self._roster()
            rows=self._read('characters.json',MAX_BYTES)['characters']
            return copy.deepcopy(rows)

    def _character(self, key):
        value = self._read(identity(key) + '.json', MAX_BYTES)
        if not isinstance(value, dict) or value.get('schema') != 'gg.local-character-save.v1':
            raise ValueError('LOCAL_CUSTODY_CHARACTER_MISSING')
        integer(value.get('revision'), 1, MAX_SEQUENCE)
        validate_payload(value.get('payload'))
        rows = value['payload'].get('item_instances')
        if not isinstance(rows, list) or len(rows) > items.MAX_WORLD_INSTANCES:
            raise ValueError('LOCAL_CUSTODY_ITEMS_INVALID')
        seen = set()
        for item in rows:
            if not isinstance(item, dict):
                raise ValueError('LOCAL_CUSTODY_ITEMS_INVALID')
            key_id = short_text(item.get('instance_id'), 64)
            if not key_id or key_id in seen:
                raise ValueError('LOCAL_CUSTODY_ITEMS_INVALID')
            seen.add(key_id)
            short_text(item.get('definition_id'), 96)
            integer(item.get('quantity'), 1, 999)
            origin(key, item)
        self._money(value['payload'])
        return value

    @staticmethod
    def _money(payload, delta=0):
        wallet = payload['economy_state']['wallet']
        value = integer(wallet.get('gold', 0), 0, 2_000_000_000) * 10000 + integer(wallet.get('copper', 0), 0, 9999)
        value = integer(value + delta)
        if delta:
            wallet['gold'], wallet['copper'] = divmod(value, 10000)
            wallet['revision'] = integer(wallet.get('revision', 0), 0, MAX_SEQUENCE - 1) + 1
        return value

    def _shared(self):
        value = self._read('shared-custody.json', MAX_SHARED_BYTES)
        return empty_shared() if value is None else value

    def _validate(self, characters, shared):
        return self._validate_shared_channels(characters, shared)

    def _validate_custody_locked(self, characters, shared):
        if not isinstance(shared, dict) or shared.get('schema') != SHARED_SCHEMA:
            raise ValueError('LOCAL_CUSTODY_SHARED_INVALID')
        integer(shared.get('revision'), 0, MAX_SEQUENCE)
        integer(shared.get('money_sinks'), 0, MAX_SEQUENCE)
        clock(shared.get('clock'))
        for field, bound in (('mail', MAX_MAIL * 10), ('auctions', MAX_AUCTIONS),
                             ('guilds', MAX_GUILDS), ('escrow', MAX_MAIL * 10 + MAX_AUCTIONS),
                             ('guild_invites', 10), ('sequences', 10), ('receipts', MAX_RECEIPTS),('retired',1024)):
            if not isinstance(shared.get(field), dict) or len(shared[field]) > bound:
                raise ValueError('LOCAL_CUSTODY_CAPACITY')
        chat=shared.get('chat',{})
        if not isinstance(chat,dict) or len(chat)>10:raise ValueError('LOCAL_CUSTODY_CHAT_CAPACITY')
        message_ids=set()
        for recipient,messages in chat.items():
            if recipient not in characters or not isinstance(messages,list) or len(messages)>MAX_CHAT_INBOX:
                raise ValueError('LOCAL_CUSTODY_CHAT_CAPACITY')
            for message in messages:
                if not isinstance(message,dict) or set(message) not in ({'id','sender','recipient','kind','text','sent'},
                        {'id','sender','recipient','kind','text','sent','expires'},
                        {'id','sender','recipient','kind','text','sent','expires','prefix','distribution'}):
                    raise ValueError('LOCAL_CUSTODY_CHAT_INVALID')
                if message['sender'] not in characters or message['recipient']!=recipient or message['sender']==recipient:
                    raise ValueError('LOCAL_CUSTODY_CHAT_INVALID')
                key=message['id']
                if not isinstance(key,str) or not key.startswith('chat-') or len(key)!=37 or any(c not in '0123456789abcdef' for c in key[5:]) or key in message_ids:
                    raise ValueError('LOCAL_CUSTODY_CHAT_INVALID')
                message_ids.add(key);clock(message['sent'])
                if message['kind'] not in ('GUILD','OFFICER','WHISPER','PARTY','RAID','ADDON'):
                    raise ValueError('LOCAL_CUSTODY_CHAT_INVALID')
                if message['kind']=='ADDON':
                    addon_payload(message.get('prefix'),message['text'],message.get('distribution'))
                    if 'expires' not in message:raise ValueError('LOCAL_CUSTODY_CHAT_INVALID')
                else:
                    short_text(message['text'],255)
                    if not message['text'].strip() or 'prefix' in message:raise ValueError('LOCAL_CUSTODY_CHAT_INVALID')
                if 'expires' in message:
                    clock(message['expires'])
                    if message['expires']!=message['sent']+GROUP_CHAT_SECONDS or message['kind'] not in ('PARTY','RAID','ADDON'):
                        raise ValueError('LOCAL_CUSTODY_CHAT_INVALID')
        claims = {}
        for mail in shared['mail'].values():
            if mail['sender'] not in characters or mail['recipient'] not in characters:
                raise ValueError('LOCAL_CUSTODY_RECIPIENT_UNAVAILABLE')
            integer(mail['money']);integer(mail['cod'])
            short_text(mail['subject'], 128);short_text(mail['body'], 4096)
            clock(mail['expires'])
            if any(type(mail.get(field)) is not bool for field in ('read','returned','permanent','system')):
                raise ValueError('LOCAL_CUSTODY_MAIL_INVALID')
            if mail['asset']:
                if mail['asset'] in claims:raise ValueError('LOCAL_CUSTODY_DUPLICATE_CLAIM')
                claims[mail['asset']] = ('MAIL', mail['recipient'])
            if mail['cod'] and (not mail['asset'] or mail['money']):
                raise ValueError('LOCAL_CUSTODY_COD_INVALID')
        for key in characters:
            local_mail=characters[key]['payload'].get('player',{}).get('client_controls',{}).get('services',{}).get('mail',[])
            local_count=sum(m.get('recipient')=='player' for m in local_mail if isinstance(m,dict))
            if local_count+sum(mail['recipient'] == key for mail in shared['mail'].values()) > MAX_MAIL:
                raise ValueError('LOCAL_CUSTODY_MAILBOX_FULL')
        for auction in shared['auctions'].values():
            if auction['owner'] not in characters or auction['bidder'] and auction['bidder'] not in characters:
                raise ValueError('LOCAL_CUSTODY_RECIPIENT_UNAVAILABLE')
            for field in ('min_bid', 'buyout', 'bid', 'deposit'):integer(auction[field])
            if auction.get('duration') not in (120, 480, 1440):raise ValueError('LOCAL_CUSTODY_AUCTION_DURATION')
            clock(auction['expires'])
            if auction['asset'] in claims:raise ValueError('LOCAL_CUSTODY_DUPLICATE_CLAIM')
            claims[auction['asset']] = ('AUCTION', auction['owner'])
        if set(claims) != set(shared['escrow']):
            raise ValueError('LOCAL_CUSTODY_ESCROW_DESYNCHRONIZED')
        assets = {}
        money = shared['money_sinks'] + sum(m['money'] for m in shared['mail'].values())
        money += sum(a['bid'] + a['deposit'] for a in shared['auctions'].values())
        for character, envelope in characters.items():
            if envelope.get('schema') != 'gg.local-character-save.v1':raise ValueError('LOCAL_CUSTODY_CHARACTER_INVALID')
            integer(envelope['revision'], 1, MAX_SEQUENCE)
            validate_payload(envelope['payload'])
            rows = envelope['payload'].get('item_instances')
            if not isinstance(rows, list) or len(rows) > items.MAX_WORLD_INSTANCES:
                raise ValueError('LOCAL_CUSTODY_ITEMS_INVALID')
            if envelope['payload']['inventory'] != items.inventory_counts(rows):
                raise ValueError('LOCAL_CUSTODY_INVENTORY_DESYNCHRONIZED')
            if len({row['instance_id'] for row in rows}) != len(rows):raise ValueError('LOCAL_CUSTODY_ITEM_ID_COLLISION')
            money += self._money(envelope['payload'])
            for item in rows:
                integer(item.get('quantity'), 1, 999)
                self._asset(assets, character, item)
        for key, item in shared['escrow'].items():
            logical_origin = origin('', item)
            if key != asset_id('', item) or (item['location'], item['owner_id']) != claims[key]:
                raise ValueError('LOCAL_CUSTODY_ESCROW_DESYNCHRONIZED')
            self._asset(assets, logical_origin['character'], item)
        membership = set()
        for guild in shared['guilds'].values():
            short_text(guild['name'], 48)
            if not isinstance(guild['members'], dict) or not 1 <= len(guild['members']) <= 10:
                raise ValueError('LOCAL_CUSTODY_GUILD_INVALID')
            if guild['leader'] not in guild['members']:
                raise ValueError('LOCAL_CUSTODY_GUILD_INVALID')
            if not isinstance(guild.get('ranks'),list) or not 5<=len(guild['ranks'])<=10:
                raise ValueError('LOCAL_CUSTODY_GUILD_INVALID')
            for rank in guild['ranks']:
                short_text(rank['name'],32);integer(rank['rights'],0,ALL_RIGHTS)
            if sum(member['rank']==0 for member in guild['members'].values())!=1 or guild['members'][guild['leader']]['rank']!=0:
                raise ValueError('LOCAL_CUSTODY_GUILD_INVALID')
            for member, value in guild['members'].items():
                if member not in characters or member in membership:
                    raise ValueError('LOCAL_CUSTODY_GUILD_MEMBERSHIP')
                integer(value['rank'], 0, len(guild['ranks'])-1)
                short_text(value['note'],255);short_text(value['officer_note'],255);membership.add(member)
                local_guild=characters[member]['payload'].get('player',{}).get('client_controls',{}).get('services',{}).get('guild',{})
                if local_guild.get('members',{}).get('player'):raise ValueError('GUILD_ALREADY_MEMBER')
        for member, invite in shared['guild_invites'].items():
            if member not in characters or member in membership or invite['guild'] not in shared['guilds']:
                raise ValueError('LOCAL_CUSTODY_GUILD_MEMBERSHIP')
            if invite['leader'] != shared['guilds'][invite['guild']]['leader']:
                raise ValueError('LOCAL_CUSTODY_GUILD_PERMISSION')
            if invite['inviter'] not in shared['guilds'][invite['guild']]['members']:
                raise ValueError('LOCAL_CUSTODY_GUILD_PERMISSION')
            clock(invite['expires'])
        self._validate_groups(characters,shared)
        petitions.validate(characters,shared)
        direct_trades.validate(characters,shared)
        for key, sequence in shared['sequences'].items():
            if key not in characters:raise ValueError('LOCAL_CUSTODY_SEQUENCE_INVALID')
            integer(sequence, 1, MAX_SEQUENCE)
        for key,record in shared['retired'].items():
            identity(key)
            if key in characters:raise ValueError('LOCAL_CUSTODY_RETIRED_CHARACTER_REUSED')
            if not isinstance(record,dict) or set(record)!={'request_hash','before','sequence'}:
                raise ValueError('LOCAL_CUSTODY_RETIREMENT_INVALID')
            if set(record['before'])!={'shared-custody.json','characters.json',key+'.json'}:
                raise ValueError('LOCAL_CUSTODY_RETIREMENT_INVALID')
            self._hash(record['request_hash']);integer(record['sequence'],0,MAX_SEQUENCE)
            for value in record['before'].values():self._hash(value)
            if digest(dict(op='CHARACTER_DELETE',character=key,before=record['before']))!=record['request_hash']:
                raise ValueError('LOCAL_CUSTODY_RETIREMENT_INVALID')
        for key, receipt in shared['receipts'].items():
            issuer, sequence = self._receipt_key(key)
            if issuer not in characters or sequence > shared['sequences'].get(issuer, 0):
                raise ValueError('LOCAL_CUSTODY_RECEIPT_INVALID')
            if not isinstance(receipt, dict) or set(receipt) != {'request_hash', 'before', 'after', 'result', 'committed_revision','request','characters','expected_revisions'}:
                raise ValueError('LOCAL_CUSTODY_RECEIPT_INVALID')
            integer(receipt['committed_revision'], 1, shared['revision'])
            self._hash(receipt['request_hash'])
            if digest(dict(issuer=issuer,sequence=sequence,request=receipt['request'],characters=receipt['characters'],expected_revisions=receipt['expected_revisions'])) != receipt['request_hash']:
                raise ValueError('LOCAL_CUSTODY_RECEIPT_INVALID')
            for values in (receipt['before'], receipt['after']):
                for value in values.values():self._hash(value)
        encoded(shared, MAX_SHARED_BYTES)
        return assets, money

    @staticmethod
    def _validate_groups(characters,shared):
        groups=shared.get('groups',{});invites=shared.get('group_invites',{})
        if not isinstance(groups,dict) or len(groups)>MAX_GROUPS or not isinstance(invites,dict) or len(invites)>10:
            raise ValueError('LOCAL_CUSTODY_GROUP_CAPACITY')
        membership=set()
        for key,group in groups.items():
            if not isinstance(key,str) or not key.startswith('group-') or len(key)!=38 or any(c not in '0123456789abcdef' for c in key[6:]):
                raise ValueError('LOCAL_CUSTODY_GROUP_INVALID')
            if not isinstance(group,dict) or set(group)!={'members','raid','leader','assistants','subgroups','loot_method','threshold','master','marks','ready'}:
                raise ValueError('LOCAL_CUSTODY_GROUP_INVALID')
            members=group['members']
            if type(group['raid']) is not bool or not isinstance(members,list) or not 1<=len(members)<=(40 if group['raid'] else 5) or any(not isinstance(m,str) for m in members) or len(set(members))!=len(members):
                raise ValueError('LOCAL_CUSTODY_GROUP_INVALID')
            for member in members:
                if member not in characters or member in membership:raise ValueError('GROUP_ALREADY_MEMBER')
                membership.add(member)
                local=characters[member]['payload'].get('player',{}).get('client_controls',{}).get('services',{}).get('group',{})
                if local.get('members'):raise ValueError('GROUP_ALREADY_MEMBER')
            if group['leader'] not in members or group['master'] not in members or group['loot_method'] not in LOOT_METHODS:
                raise ValueError('LOCAL_CUSTODY_GROUP_INVALID')
            integer(group['threshold'],2,4)
            assistants=group['assistants']
            if not isinstance(assistants,list) or any(not isinstance(m,str) for m in assistants) or len(set(assistants))!=len(assistants) or any(m not in members or m==group['leader'] for m in assistants) or assistants and not group['raid']:
                raise ValueError('LOCAL_CUSTODY_GROUP_INVALID')
            if not isinstance(group['subgroups'],dict) or set(group['subgroups'])!=set(members):raise ValueError('LOCAL_CUSTODY_GROUP_INVALID')
            for value in group['subgroups'].values():integer(value,1,8)
            if any(sum(value==i for value in group['subgroups'].values())>5 for i in range(1,9)) or not group['raid'] and any(v!=1 for v in group['subgroups'].values()):
                raise ValueError('GROUP_SUBGROUP_FULL')
            marks=group['marks']
            if not isinstance(marks,dict) or any(m not in members for m in marks):raise ValueError('LOCAL_CUSTODY_GROUP_INVALID')
            for value in marks.values():integer(value,0,8)
            active_marks=[v for v in marks.values() if v]
            if len(set(active_marks))!=len(active_marks):raise ValueError('LOCAL_CUSTODY_GROUP_INVALID')
            ready=group['ready']
            if ready:
                if not isinstance(ready,dict) or set(ready)!={'id','initiator','expires','answers','finished'} or ready['initiator'] not in members or type(ready['finished']) is not bool:
                    raise ValueError('LOCAL_CUSTODY_GROUP_READY_INVALID')
                short_text(ready['id'],64);clock(ready['expires'])
                if not isinstance(ready['answers'],dict) or set(ready['answers'])!=set(members) or any(v is not None and type(v) is not bool for v in ready['answers'].values()):raise ValueError('LOCAL_CUSTODY_GROUP_READY_INVALID')
            elif ready!={}:raise ValueError('LOCAL_CUSTODY_GROUP_READY_INVALID')
        for member,offer in invites.items():
            if member not in characters or member in membership or not isinstance(offer,dict) or set(offer)!={'group','leader','inviter','expires'}:
                raise ValueError('LOCAL_CUSTODY_GROUP_INVITATION_INVALID')
            group=groups.get(offer['group'])
            if not group or offer['leader']!=group['leader'] or offer['inviter']!=group['leader']:
                raise ValueError('GROUP_LEADER_REQUIRED')
            clock(offer['expires'])

    @staticmethod
    def _hash(value):
        if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
            raise ValueError('LOCAL_CUSTODY_HASH_INVALID')

    @staticmethod
    def _receipt_key(key):
        if not isinstance(key, str) or key.count(':') != 1:
            raise ValueError('LOCAL_CUSTODY_RECEIPT_INVALID')
        issuer, sequence = key.split(':')
        identity(issuer)
        if not sequence.isdigit() or str(int(sequence)) != sequence:
            raise ValueError('LOCAL_CUSTODY_RECEIPT_INVALID')
        return issuer, integer(int(sequence), 1, MAX_SEQUENCE)

    @staticmethod
    def _asset(assets, character, item):
        key = asset_id(character, item)
        if key in assets:raise ValueError('LOCAL_CUSTODY_DUPLICATE_ASSET')
        immutable = {k: v for k, v in item.items() if k not in CONTEXT_FIELDS}
        assets[key] = digest(immutable)

    @staticmethod
    def _letter_credit(before_assets,after_assets,before_shared,shared,characters,issuer,request,source_id):
        source=before_shared['mail'].get(source_id);current=shared['mail'].get(source_id)
        added=set(after_assets)-set(before_assets)
        if (request != {'op':'MAIL_TEXT','mail':source_id}
                or not source or source['recipient'] != issuer or source['permanent'] or not source['body']
                or not current or not current['permanent'] or len(added)!=1):
            raise ValueError('LOCAL_CUSTODY_LETTER_ENTITLEMENT')
        expected_letter=dict(subject=source['subject'],body=source['body'],sender=source['sender'])
        candidate=next((i for i in characters[issuer]['payload']['item_instances'] if asset_id(issuer,i) in added),None)
        wanted='letter-'+digest(dict(recipient=issuer,mail=source_id))[:32]
        if (not candidate or candidate['instance_id']!=wanted or candidate['definition_id']!='item.gg_letter'
                or candidate['quantity']!=1 or candidate.get('letter')!=expected_letter):
            raise ValueError('LOCAL_CUSTODY_LETTER_ENTITLEMENT')
        before_assets.update({key:after_assets[key] for key in added})

    def _recover_locked(self):
        try:
            journal = self._read('shared-custody.pending.json', MAX_JOURNAL_BYTES)
        except Exception as error:
            raise RecoveryRequired('', error) from error
        if journal is None:return {'status': 'CLEAN'}
        receipt = journal.get('receipt', '') if isinstance(journal, dict) else ''
        try:
            if isinstance(journal,dict) and journal.get('schema')==RETIREMENT_SCHEMA:
                return self._recover_retirement_locked(journal)
            fields = {'schema', 'receipt', 'targets', 'request_hash','letter_source'}
            if journal.get('schema') != JOURNAL_SCHEMA or set(journal) not in (fields, fields | {'petition_source'}):
                raise ValueError('LOCAL_CUSTODY_JOURNAL_INVALID')
            self._receipt_key(receipt);self._hash(journal['request_hash'])
            targets = journal['targets']
            if not isinstance(targets, list) or not 1 <= len(targets) <= 3:
                raise ValueError('LOCAL_CUSTODY_JOURNAL_INVALID')
            names = [t['name'] for t in targets]
            if len(set(names)) != len(names) or names[-1] != 'shared-custody.json':
                raise ValueError('LOCAL_CUSTODY_JOURNAL_INVALID')
            roster = self._roster()
            characters = {key: self._character(key) for key in roster}
            before_characters = copy.deepcopy(characters)
            for target in targets:
                name = target['name'];self._path(name)
                if set(target) != {'name', 'before', 'after', 'value', 'before_value'}:
                    raise ValueError('LOCAL_CUSTODY_JOURNAL_INVALID')
                self._hash(target['before']);self._hash(target['after'])
                if digest(target['value']) != target['after'] or digest(target['before_value']) != target['before']:
                    raise ValueError('LOCAL_CUSTODY_JOURNAL_INVALID')
                if name != 'shared-custody.json':
                    if name[:-5] not in characters:raise ValueError('LOCAL_CUSTODY_CHARACTER_MISSING')
                    validate_payload(target['value']['payload'])
                    if target['value']['revision'] != target['before_value']['revision'] + 1:
                        raise ValueError('LOCAL_CUSTODY_REVISION_INVALID')
                    if target['value']['payload'].get('character_appearance') != target['before_value']['payload'].get('character_appearance'):
                        raise ValueError('LOCAL_CUSTODY_APPEARANCE_CHANGED')
                    characters[name[:-5]] = target['value']
                    before_characters[name[:-5]] = target['before_value']
            shared = targets[-1]['value']
            before_shared = targets[-1]['before_value'] or empty_shared()
            if shared['revision'] != before_shared['revision'] + 1:
                raise ValueError('LOCAL_CUSTODY_REVISION_INVALID')
            stored = shared['receipts'].get(receipt)
            if not stored or stored['request_hash'] != journal['request_hash']:
                raise ValueError('LOCAL_CUSTODY_JOURNAL_INVALID')
            after_assets,after_money=self._validate(characters,shared)
            before_assets,before_money=self._validate(before_characters,before_shared)
            if journal['letter_source'] is not None:
                self._letter_credit(before_assets,after_assets,before_shared,shared,characters,receipt.split(':')[0],stored['request'],journal['letter_source'])
            if 'petition_source' in journal:
                issuer, sequence = self._receipt_key(receipt)
                names = {r['id']:r['name'] for r in self._read('characters.json',MAX_BYTES)['characters']}
                petitions.prove(before_assets,after_assets,before_characters,characters,before_shared,shared,
                                issuer,sequence,stored['request'],journal['petition_source'],names=names,result=stored['result'])
            if isinstance(stored['request'],dict) and stored['request'].get('op')=='DIRECT_TRADE_ACTION':
                issuer, sequence = self._receipt_key(receipt)
                names = {r['id']:r['name'] for r in self._read('characters.json',MAX_BYTES)['characters']}
                direct_trades.prove(before_characters,characters,before_shared,shared,issuer,sequence,
                                    stored['request'],names=names,result=stored['result'],
                                    before_assets=before_assets,after_assets=after_assets)
            if isinstance(stored['request'],dict) and stored['request'].get('op')=='CHANNEL_ACTION':
                issuer, sequence = self._receipt_key(receipt)
                names = {r['id']:r['name'] for r in self._read('characters.json',MAX_BYTES)['characters']}
                shared_channels.prove(before_characters,characters,before_shared,shared,issuer,sequence,
                                      stored['request'],names=names,result=stored['result'])
            if (before_assets,before_money)!=(after_assets,after_money):raise ValueError('LOCAL_CUSTODY_CONSERVATION')
            if stored['before'] != {t['name']: t['before'] for t in targets}:
                raise ValueError('LOCAL_CUSTODY_JOURNAL_INVALID')
            if stored['after'] != {t['name']: t['after'] for t in targets[:-1]}:
                raise ValueError('LOCAL_CUSTODY_JOURNAL_INVALID')
            # Validate ALL destinations before replacing ANY.  A different old
            # writer must never be silently overwritten by recovery.
            for target in targets:
                limit = MAX_SHARED_BYTES if target['name'] == 'shared-custody.json' else MAX_BYTES
                current = self._read(target['name'], limit)
                if digest(current) not in (target['before'], target['after']):
                    raise ValueError('LOCAL_CUSTODY_RECOVERY_CONFLICT')
            # An fsync failure after intent replacement is uncertain until
            # this mandatory recovery makes the actual intent durable again.
            fd = secure_open(self._path('shared-custody.pending.json'), os.O_RDONLY | NOFOLLOW)
            try:os.fsync(fd)
            finally:os.close(fd)
            self._sync_directory()
            for target in targets:
                limit = MAX_SHARED_BYTES if target['name'] == 'shared-custody.json' else MAX_BYTES
                self._write(target['name'], target['value'], limit)
            self._fault('before_clear', 'shared-custody.pending.json')
            os.unlink(self._path('shared-custody.pending.json'))
            self._fault('journal_removed', 'shared-custody.pending.json')
            self._sync_directory()
            return {'status': 'COMMITTED', 'receipt': receipt, 'result': copy.deepcopy(stored['result'])}
        except Exception as error:
            raise RecoveryRequired(receipt, error) from error

    def recover(self):
        with self._locked():return self._recover_locked()

    def snapshot(self):
        with self._locked():
            recovered=self._recover_locked()
            characters = {key: self._character(key) for key in self._roster()}
            shared = self._shared();self._validate(characters, shared)
            return {'characters': characters, 'shared': shared,'recovery':recovered}

    def validate_save(self,character,payload):
        """CharacterStore before-save guard, not a replacement for journaling."""
        identity(character)
        with self._locked():
            if self._path('shared-custody.pending.json').exists():
                raise RecoveryRequired('',ValueError('LOCAL_CUSTODY_PENDING_SAVE_FORBIDDEN'))
            registry=self._read('characters.json',MAX_BYTES)
            if registry is None and self._read('shared-custody.json',MAX_SHARED_BYTES) is None:
                # LocalCharacters' first migration writes its new envelope
                # before publishing the first registry row, under this lock.
                validate_payload(payload)
                if self._read(character+'.json',MAX_BYTES) is not None:raise ValueError('LOCAL_CUSTODY_CHARACTER_MISSING')
                return
            characters={key:self._character(key) for key in self._roster()}
            if character not in characters:raise ValueError('LOCAL_CUSTODY_CHARACTER_MISSING')
            candidate=copy.deepcopy(characters[character]);candidate['payload']=copy.deepcopy(payload)
            characters[character]=candidate
            self._validate(characters,self._shared())

    @staticmethod
    def _delete_blockers(character, shared, *, include_history=False, characters=None):
        blockers = []
        if any(character in (m['sender'], m['recipient']) for m in shared['mail'].values()):blockers.append('MAIL')
        if any(character in (a['owner'], a['bidder']) for a in shared['auctions'].values()):blockers.append('AUCTION')
        if any(character in g['members'] for g in shared['guilds'].values()):blockers.append('GUILD')
        if character in shared['guild_invites'] or any(character in (i['leader'],i['inviter']) for i in shared['guild_invites'].values()):blockers.append('GUILD_INVITATION')
        if any(character in g['members'] for g in shared.get('groups',{}).values()):blockers.append('GROUP')
        if character in shared.get('group_invites',{}) or any(character in (i['leader'],i['inviter']) for i in shared.get('group_invites',{}).values()):blockers.append('GROUP_INVITATION')
        if any(character in (i['owner_id'], origin('', i)['character']) for i in shared['escrow'].values()):blockers.append('ESCROW')
        if any(character in (m['sender'],m['recipient']) for inbox in shared.get('chat',{}).values() for m in inbox):blockers.append('CHAT')
        if include_history and (character in shared['sequences'] or any(k.startswith(character + ':') for k in shared['receipts'])):blockers.append('TRANSACTION_HISTORY')
        if characters is not None:blockers.extend(petitions.delete_blockers(character,characters,shared))
        if characters is not None:blockers.extend(direct_trades.delete_blockers(character,characters,shared))
        blockers.extend(shared_channels.delete_blockers(character,shared))
        return blockers

    def can_delete(self, character, *, include_history=True):
        """Read-only preview; confirmed deletion retires history in the journal."""
        identity(character)
        value = self.snapshot()
        if character not in value['characters']:raise ValueError('LOCAL_CUSTODY_CHARACTER_MISSING')
        blockers=self._delete_blockers(character,value['shared'],include_history=include_history,characters=value['characters'])
        return {'allowed': not blockers, 'blockers': blockers}

    def delete_character(self,character):
        """Coordinate confirmed profile deletion, roster, and bounded replay retirement.

        Only the character's own profile is deleted.  Shared assets or social
        references must first be collected/returned/disbanded explicitly.
        A retained namespace tombstone prevents identity/receipt resurrection.
        """
        identity(character)
        with self._locked():
            self._recover_locked()
            shared_before=self._read('shared-custody.json',MAX_SHARED_BYTES)
            shared=copy.deepcopy(shared_before or empty_shared())
            registry=self._read('characters.json',MAX_BYTES)
            roster=self._roster();characters={key:self._character(key) for key in roster}
            self._validate(characters,shared)
            if character in shared['retired']:
                return {'status':'COMMITTED','receipt':'delete:'+character,'replayed':True,
                        'rows':registry['characters']}
            if character not in characters:raise ValueError('LOCAL_CUSTODY_CHARACTER_MISSING')
            blockers=self._delete_blockers(character,shared,characters=characters)
            if blockers:raise ValueError('LOCAL_CUSTODY_DELETE_REFERENCES:'+','.join(blockers))
            after_registry=copy.deepcopy(registry)
            after_registry['characters']=[r for r in registry['characters'] if r['id']!=character]
            before_values={'shared-custody.json':shared_before,'characters.json':registry,character+'.json':characters[character]}
            before={name:digest(value) for name,value in before_values.items()}
            request_hash=digest(dict(op='CHARACTER_DELETE',character=character,before=before))
            shared['retired'][character]=dict(request_hash=request_hash,before=before,sequence=shared['sequences'].pop(character,0))
            shared['receipts']={k:v for k,v in shared['receipts'].items() if not k.startswith(character+':')}
            shared['revision']=integer(shared['revision'],0,MAX_SEQUENCE-1)+1
            remaining={k:v for k,v in characters.items() if k!=character};self._validate(remaining,shared)
            after_values={'shared-custody.json':shared,'characters.json':after_registry,character+'.json':None}
            targets=[dict(name=name,before=before[name],after=digest(value),before_value=before_values[name],value=value)
                     for name,value in after_values.items()]
            journal=dict(schema=RETIREMENT_SCHEMA,receipt='delete:'+character,character=character,request_hash=request_hash,targets=targets)
            try:self._write('shared-custody.pending.json',journal,MAX_JOURNAL_BYTES)
            except Exception as error:
                if self._path('shared-custody.pending.json').exists():raise RecoveryRequired('delete:'+character,error) from error
                raise
            self._recover_locked()
            return {'status':'COMMITTED','receipt':'delete:'+character,'replayed':False,'rows':after_registry['characters']}

    def _recover_retirement_locked(self,journal):
        if set(journal)!={'schema','receipt','character','request_hash','targets'}:raise ValueError('LOCAL_CUSTODY_JOURNAL_INVALID')
        character=identity(journal['character'])
        if journal['receipt']!='delete:'+character:raise ValueError('LOCAL_CUSTODY_JOURNAL_INVALID')
        targets=journal['targets']
        if not isinstance(targets,list) or [t['name'] for t in targets]!=['shared-custody.json','characters.json',character+'.json']:
            raise ValueError('LOCAL_CUSTODY_JOURNAL_INVALID')
        for target in targets:
            if set(target)!={'name','before','after','before_value','value'}:raise ValueError('LOCAL_CUSTODY_JOURNAL_INVALID')
            self._path(target['name'])
            if digest(target['before_value'])!=target['before'] or digest(target['value'])!=target['after']:
                raise ValueError('LOCAL_CUSTODY_JOURNAL_INVALID')
        shared_target,registry_target,character_target=targets
        registry=registry_target['before_value']
        if registry.get('schema')!='gg.local-characters.v1' or not isinstance(registry.get('characters'),list):
            raise ValueError('LOCAL_CUSTODY_ROSTER_INVALID')
        before_ids=[identity(r['id']) for r in registry['characters']]
        if len(set(before_ids))!=len(before_ids) or character not in before_ids or len(before_ids)>10:
            raise ValueError('LOCAL_CUSTODY_ROSTER_INVALID')
        expected_registry=copy.deepcopy(registry)
        expected_registry['characters']=[r for r in registry['characters'] if r['id']!=character]
        if expected_registry!=registry_target['value'] or character_target['value'] is not None:
            raise ValueError('LOCAL_CUSTODY_JOURNAL_INVALID')
        before={t['name']:t['before'] for t in targets}
        wanted=digest(dict(op='CHARACTER_DELETE',character=character,before=before))
        if wanted!=journal['request_hash']:raise ValueError('LOCAL_CUSTODY_JOURNAL_INVALID')
        before_shared=shared_target['before_value'] or empty_shared()
        remaining={key:self._character(key) for key in before_ids if key!=character}
        before_characters=dict(remaining,**{character:character_target['before_value']})
        if self._delete_blockers(character,before_shared,characters=before_characters):raise ValueError('LOCAL_CUSTODY_DELETE_REFERENCES')
        expected_shared=copy.deepcopy(before_shared)
        expected_shared['retired'][character]=dict(request_hash=wanted,before=before,sequence=expected_shared['sequences'].pop(character,0))
        expected_shared['receipts']={k:v for k,v in expected_shared['receipts'].items() if not k.startswith(character+':')}
        expected_shared['revision']+=1
        if expected_shared!=shared_target['value']:raise ValueError('LOCAL_CUSTODY_JOURNAL_INVALID')
        self._validate(before_characters,before_shared)
        self._validate(remaining,expected_shared)
        # No remaining item/wallet/social state is allowed to change.
        for target in targets:
            limit=MAX_SHARED_BYTES if target['name']=='shared-custody.json' else MAX_BYTES
            if digest(self._read(target['name'],limit)) not in (target['before'],target['after']):
                raise ValueError('LOCAL_CUSTODY_RECOVERY_CONFLICT')
        fd=secure_open(self._path('shared-custody.pending.json'),os.O_RDONLY|NOFOLLOW)
        try:os.fsync(fd)
        finally:os.close(fd)
        self._sync_directory()
        for target in targets:
            if target['value'] is None:
                self._fault('before_delete',target['name'])
                self._path(target['name']).unlink(missing_ok=True)
                self._fault('deleted',target['name']);self._sync_directory()
                self._fault('directory_synced',target['name'])
            else:self._write(target['name'],target['value'],MAX_SHARED_BYTES if target['name']=='shared-custody.json' else MAX_BYTES)
        self._fault('before_clear','shared-custody.pending.json')
        self._path('shared-custody.pending.json').unlink()
        self._fault('journal_removed','shared-custody.pending.json');self._sync_directory()
        return {'status':'COMMITTED','receipt':'delete:'+character,'character_deleted':character,'rows':expected_registry['characters']}

    def transact(self, issuer, sequence, request, character_ids, transform, *, expected_revisions=None, _letter_source=None, _petition_source=None):
        """Transform at most two existing payloads and shared custody atomically.

        transform(payloads, shared) returns finite JSON metadata.  Conservation
        is enforced over the entire roster, not only the selected characters.
        No caller appearance decorator runs.  Expected revisions belong to the
        immutable command, so a replay cannot target a newer UI observation.
        """
        identity(issuer);integer(sequence, 1, MAX_SEQUENCE)
        if not isinstance(character_ids, (list, tuple)) or len(character_ids) > 2:
            raise ValueError('LOCAL_CUSTODY_TRANSACTION_CAPACITY')
        keys = sorted(identity(key) for key in character_ids)
        if len(set(keys)) != len(keys):raise ValueError('LOCAL_CUSTODY_TRANSACTION_CAPACITY')
        expected = {} if expected_revisions is None else copy.deepcopy(expected_revisions)
        if not isinstance(expected, dict) or set(expected) - set(keys):raise ValueError('LOCAL_CUSTODY_REVISION_INVALID')
        for value in expected.values():integer(value, 1, MAX_SEQUENCE)
        encoded(request, 65536)
        request_hash = digest(dict(issuer=issuer, sequence=sequence, request=request,
                                   characters=keys, expected_revisions=expected))
        receipt_id = issuer + ':' + str(sequence)
        with self._locked():
            self._recover_locked()
            characters = {key: self._character(key) for key in self._roster()}
            if issuer not in characters or set(keys) - set(characters):raise ValueError('LOCAL_CUSTODY_CHARACTER_MISSING')
            shared = self._shared()
            before_assets, before_money = self._validate(characters, shared)
            direct_trade_request = isinstance(request,dict) and request.get('op')=='DIRECT_TRADE_ACTION'
            channel_request = isinstance(request,dict) and request.get('op')=='CHANNEL_ACTION'
            before_characters = copy.deepcopy(characters) if _petition_source is not None or direct_trade_request or channel_request else None
            prior = shared['receipts'].get(receipt_id)
            if prior:
                if prior['request_hash'] != request_hash:raise ValueError('LOCAL_CUSTODY_REPLAY_CHANGED')
                return {'status': 'COMMITTED', 'receipt': receipt_id, 'replayed': True, 'result': copy.deepcopy(prior['result'])}
            if sequence <= shared['sequences'].get(issuer, 0):raise ValueError('LOCAL_CUSTODY_RECEIPT_EXPIRED')
            for key, revision in expected.items():
                if characters[key]['revision'] != revision:raise ValueError('LOCAL_CUSTODY_REVISION_CHANGED')
            before = {key + '.json': digest(characters[key]) for key in keys}
            before_values = {key + '.json': copy.deepcopy(characters[key]) for key in keys}
            before_values['shared-custody.json'] = self._read('shared-custody.json', MAX_SHARED_BYTES)
            before['shared-custody.json'] = digest(before_values['shared-custody.json'])
            payloads = {key: copy.deepcopy(characters[key]['payload']) for key in keys}
            shared = copy.deepcopy(shared)
            result = transform(payloads, shared)
            encoded(result, 16384)
            for field in ('revision', 'sequences', 'receipts','retired'):
                old = before_values['shared-custody.json'] or empty_shared()
                if shared[field] != old[field]:raise ValueError('LOCAL_CUSTODY_RESERVED_FIELD_CHANGED')
            for key in keys:
                validate_payload(payloads[key])
                if payloads[key].get('character_appearance') != characters[key]['payload'].get('character_appearance'):
                    raise ValueError('LOCAL_CUSTODY_APPEARANCE_CHANGED')
                characters[key] = {'schema': 'gg.local-character-save.v1',
                                   'revision': integer(characters[key]['revision'], 1, MAX_SEQUENCE - 1) + 1,
                                   'payload': payloads[key]}
                encoded(characters[key], MAX_BYTES)
            after_assets, after_money = self._validate(characters, shared)
            if _letter_source is not None:
                # The original MailText behavior materializes one GG letter
                # from one actual unread message, not market inventory.  Its
                # immutable message is the finite issuance entitlement.
                if keys != [issuer]:raise ValueError('LOCAL_CUSTODY_LETTER_ENTITLEMENT')
                self._letter_credit(before_assets,after_assets,before_values['shared-custody.json'] or empty_shared(),shared,characters,issuer,request,_letter_source)
            if _petition_source is not None:
                names = {r['id']:r['name'] for r in self._read('characters.json',MAX_BYTES)['characters']}
                petitions.prove(before_assets,after_assets,before_characters,characters,
                    before_values['shared-custody.json'] or empty_shared(),shared,issuer,sequence,request,_petition_source,names=names,result=result)
            if direct_trade_request:
                names = {r['id']:r['name'] for r in self._read('characters.json',MAX_BYTES)['characters']}
                direct_trades.prove(before_characters,characters,before_values['shared-custody.json'] or empty_shared(),
                                    shared,issuer,sequence,request,names=names,result=result,
                                    before_assets=before_assets,after_assets=after_assets)
            if channel_request:
                names = {r['id']:r['name'] for r in self._read('characters.json',MAX_BYTES)['characters']}
                shared_channels.prove(before_characters,characters,before_values['shared-custody.json'] or empty_shared(),
                                      shared,issuer,sequence,request,names=names,result=result)
            if before_assets != after_assets:raise ValueError('LOCAL_CUSTODY_ITEM_CONSERVATION')
            if before_money != after_money:raise ValueError('LOCAL_CUSTODY_MONEY_CONSERVATION')
            shared['revision'] = integer(shared['revision'], 0, MAX_SEQUENCE - 1) + 1
            shared['sequences'][issuer] = sequence
            after = {key + '.json': digest(characters[key]) for key in keys}
            shared['receipts'][receipt_id] = dict(request_hash=request_hash, before=before, after=after,
                                                 result=result, committed_revision=shared['revision'],
                                                 request=copy.deepcopy(request),characters=keys,expected_revisions=expected)
            if len(shared['receipts']) > MAX_RECEIPTS:
                oldest = min(shared['receipts'], key=lambda key: shared['receipts'][key]['committed_revision'])
                del shared['receipts'][oldest]
            self._validate(characters, shared)
            targets = [dict(name=key + '.json', before=before[key + '.json'], after=after[key + '.json'], value=characters[key], before_value=before_values[key + '.json']) for key in keys]
            targets.append(dict(name='shared-custody.json', before=before['shared-custody.json'], after=digest(shared), value=shared, before_value=before_values['shared-custody.json']))
            journal = dict(schema=JOURNAL_SCHEMA, receipt=receipt_id, request_hash=request_hash, targets=targets,letter_source=_letter_source)
            if _petition_source is not None:journal['petition_source']=_petition_source
            encoded(journal, MAX_JOURNAL_BYTES)
            try:
                self._write('shared-custody.pending.json', journal, MAX_JOURNAL_BYTES)
            except Exception as error:
                # Replacement can succeed before directory fsync throws.  A
                # readable exact intent means the caller MUST NOT roll back.
                if self._path('shared-custody.pending.json').exists():
                    raise RecoveryRequired(receipt_id, error) from error
                raise
            self._recover_locked()
            return {'status': 'COMMITTED', 'receipt': receipt_id, 'replayed': False, 'result': copy.deepcopy(result)}

    @staticmethod
    def _sync_inventory(payload):
        payload['inventory'] = items.inventory_counts(payload['item_instances'])

    @staticmethod
    def _take(payload, character, item_id, catalog, location):
        item = next((row for row in payload['item_instances'] if row['instance_id'] == item_id), None)
        ok, result = trade.validate_offer(item, items.definition(catalog, item.get('definition_id')) if item else None,
                                          owner_id='player', location='INVENTORY')
        if not ok:raise ValueError(result['error'])
        payload['item_instances'].remove(item)
        item['custody_origin'] = origin(character, item)
        item.update(location=location, owner_id=character, equipped_slot='', slot_index=-1, container_id='')
        LocalCustodyStore._sync_inventory(payload)
        return item

    @staticmethod
    def _mail(shared, mail_id, sender, recipient, subject, *, asset='', money=0, cod=0, body='', system=False, invoice=None):
        if mail_id in shared['mail']:raise ValueError('LOCAL_CUSTODY_MAIL_ID_USED')
        shared['mail'][mail_id] = dict(sender=sender, recipient=recipient, subject=subject, body=body,
                                     asset=asset, money=money, cod=cod, returned=False, read=False,
                                     permanent=False, system=system, invoice=invoice,
                                     expires=shared['clock'] + 30 * 86400)

    def send_mail(self, issuer, sequence, recipient, *, catalog, item_id='', money=0, cod=0,
                  subject='', body='', expected_revision=None, now=None):
        identity(recipient);integer(money);integer(cod)
        short_text(item_id, 64);short_text(subject, 128);short_text(body, 4096)
        if cod and (money or not item_id):raise ValueError('LOCAL_CUSTODY_COD_INVALID')
        # Receipt inputs omit the trusted ticking wall clock; every actual
        # before/final image and persisted monotonic clock remain hashed.
        moment = clock(time.time() if now is None else now)
        request = dict(op='MAIL_SEND', recipient=recipient, item=item_id, money=money, cod=cod, subject=subject, body=body)
        def apply(payloads, shared):
            shared['clock'] = max(shared['clock'], moment)
            payload = payloads[issuer]
            self._money(payload, -(money + 30));shared['money_sinks'] += 30
            key = ''
            if item_id:
                item = self._take(payload, issuer, item_id, catalog, 'MAIL')
                item['owner_id'] = recipient;key = asset_id(issuer, item)
                shared['escrow'][key] = item
            mail_id = issuer + ':' + str(sequence)
            self._mail(shared, mail_id, issuer, recipient, subject, asset=key, money=money, cod=cod, body=body)
            return dict(mail=mail_id, asset=key)
        return self.transact(issuer, sequence, request, [issuer], apply,
                             expected_revisions={} if expected_revision is None else {issuer: expected_revision})

    def collect_mail(self, issuer, sequence, mail_id, *, collect='ALL', expected_revision=None, now=None):
        if collect not in ('ALL', 'ITEM', 'MONEY'):raise ValueError('LOCAL_CUSTODY_COLLECTION_INVALID')
        short_text(mail_id, 128)
        moment = clock(time.time() if now is None else now)
        def apply(payloads, shared):
            shared['clock'] = max(shared['clock'], moment)
            mail = shared['mail'].get(mail_id)
            if not mail or mail['recipient'] != issuer:raise ValueError('LOCAL_CUSTODY_MAIL_CHANGED')
            if mail['expires'] <= shared['clock'] and not mail['system'] and not mail['returned']:raise ValueError('LOCAL_CUSTODY_MAIL_EXPIRED')
            payload = payloads[issuer];received = ''
            if collect in ('ALL', 'ITEM') and mail['asset']:
                if len(payload['item_instances']) >= items.MAX_WORLD_INSTANCES:raise ValueError('LOCAL_CUSTODY_WORLD_FULL')
                inventory = [row for row in payload['item_instances'] if row['location'] == 'INVENTORY' and row['owner_id'] == 'player']
                if len(inventory) >= items.MAX_INVENTORY_SLOTS:raise ValueError('LOCAL_CUSTODY_INVENTORY_FULL')
                used = {row.get('slot_index') for row in inventory}
                slots = set(range(items.MAX_INVENTORY_SLOTS)) - used
                if not slots:raise ValueError('LOCAL_CUSTODY_INVENTORY_FULL')
                if mail['cod']:
                    self._money(payload, -mail['cod'])
                    self._mail(shared, issuer + ':' + str(sequence) + ':cod', issuer, mail['sender'], 'Postförskott', money=mail['cod'])
                item = shared['escrow'].pop(mail['asset'])
                ids = {row['instance_id'] for row in payload['item_instances']}
                if item['instance_id'] in ids:item['instance_id'] = mail['asset']
                if item['instance_id'] in ids:raise ValueError('LOCAL_CUSTODY_ITEM_ID_COLLISION')
                item.update(location='INVENTORY', owner_id='player', slot_index=min(slots), container_id='', equipped_slot='')
                received = item['instance_id'];payload['item_instances'].append(item)
                mail['asset'] = '';mail['cod'] = 0;self._sync_inventory(payload)
                mail['read'] = True
            if collect in ('ALL', 'MONEY') and mail['money']:
                self._money(payload, mail['money']);mail['money'] = 0
            return dict(mail=mail_id, item=received)
        return self.transact(issuer, sequence, dict(op='MAIL_COLLECT', mail=mail_id, collect=collect), [issuer], apply,
                             expected_revisions={} if expected_revision is None else {issuer: expected_revision})

    def post_auction(self, issuer, sequence, item_id, *, catalog, min_bid, buyout=0, duration=120, now=None):
        integer(min_bid, 1);integer(buyout)
        integer(duration, 120, 1440)
        if duration not in (120, 480, 1440):raise ValueError('LOCAL_CUSTODY_AUCTION_DURATION')
        if buyout and buyout < min_bid:raise ValueError('LOCAL_CUSTODY_AUCTION_PRICE')
        moment = clock(time.time() if now is None else now)
        def apply(payloads, shared):
            shared['clock'] = max(shared['clock'], moment)
            deposit = max(1, min_bid // 20) * (duration // 120)
            self._money(payloads[issuer], -deposit)
            item = self._take(payloads[issuer], issuer, item_id, catalog, 'AUCTION')
            key = asset_id(issuer, item);shared['escrow'][key] = item
            auction_id = issuer + ':' + str(sequence)
            shared['auctions'][auction_id] = dict(owner=issuer, asset=key, min_bid=min_bid, buyout=buyout,
                                                 bid=0, bidder='', deposit=deposit, duration=duration,
                                                 expires=shared['clock'] + duration * 60)
            return dict(auction=auction_id, asset=key)
        return self.transact(issuer, sequence, dict(op='AUCTION_POST', item=item_id, min_bid=min_bid, buyout=buyout,duration=duration), [issuer], apply)

    def bid_auction(self, issuer, sequence, auction_id, amount, *, now=None):
        integer(amount, 1);short_text(auction_id, 128)
        moment = clock(time.time() if now is None else now)
        def apply(payloads, shared):
            shared['clock'] = max(shared['clock'], moment)
            auction = shared['auctions'].get(auction_id)
            if not auction or auction['owner'] == issuer:raise ValueError('LOCAL_CUSTODY_AUCTION_UNAVAILABLE')
            if auction['expires'] <= shared['clock']:raise ValueError('LOCAL_CUSTODY_AUCTION_EXPIRED')
            bid = min(amount, auction['buyout']) if auction['buyout'] else amount
            minimum = auction['bid'] + max(1, auction['bid'] // 20) if auction['bid'] else auction['min_bid']
            if bid < minimum and bid != auction['buyout']:raise ValueError('LOCAL_CUSTODY_BID_TOO_LOW')
            delta = bid - auction['bid'] if auction['bidder'] == issuer else bid
            self._money(payloads[issuer], -delta)
            if auction['bidder'] and auction['bidder'] != issuer:
                self._mail(shared, issuer + ':' + str(sequence) + ':refund', auction['owner'], auction['bidder'], 'Överbjuden', money=auction['bid'], system=True)
            auction.update(bid=bid, bidder=issuer)
            if auction['buyout'] and bid == auction['buyout']:
                self._finish_auction(shared, auction_id, issuer + ':' + str(sequence))
            return dict(auction=auction_id, bid=bid)
        return self.transact(issuer, sequence, dict(op='AUCTION_BID', auction=auction_id, amount=amount), [issuer], apply)

    def _finish_auction(self, shared, auction_id, mail_prefix, cancel=False):
        auction = shared['auctions'].pop(auction_id)
        sold = bool(auction['bidder']) and not cancel
        recipient = auction['bidder'] if sold else auction['owner']
        item = shared['escrow'][auction['asset']];item.update(location='MAIL', owner_id=recipient)
        self._mail(shared, mail_prefix + ':item', auction['owner'], recipient, 'Auktion', asset=auction['asset'], system=True)
        if sold:
            cut = auction['bid'] // 20
            shared['money_sinks'] += cut
            invoice = dict(item_name=item['name'], player_name=auction['bidder'], bid=auction['bid'], buyout=auction['buyout'],deposit=auction['deposit'],consignment=cut,seller=True)
            self._mail(shared, mail_prefix + ':proceeds', auction['owner'], auction['owner'], 'Såld auktion', money=auction['bid'] - cut + auction['deposit'],system=True,invoice=invoice)
        else:
            shared['money_sinks'] += auction['deposit']
            if auction['bidder']:
                self._mail(shared, mail_prefix + ':refund', auction['owner'], auction['bidder'], 'Återbetalat bud', money=auction['bid'],system=True)

    def finish_auction(self, issuer, sequence, auction_id, *, cancel=False, now=None):
        if type(cancel) is not bool:raise ValueError('LOCAL_CUSTODY_BOOLEAN_INVALID')
        moment = clock(time.time() if now is None else now)
        def apply(payloads, shared):
            shared['clock'] = max(shared['clock'], moment)
            auction = shared['auctions'].get(auction_id)
            if not auction or auction['owner'] != issuer:raise ValueError('LOCAL_CUSTODY_AUCTION_NOT_YOURS')
            if not cancel and auction['expires'] > shared['clock']:raise ValueError('LOCAL_CUSTODY_AUCTION_NOT_EXPIRED')
            self._finish_auction(shared, auction_id, issuer + ':' + str(sequence), cancel)
            return dict(auction=auction_id)
        return self.transact(issuer, sequence, dict(op='AUCTION_FINISH', auction=auction_id, cancel=cancel), [], apply)

    def create_guild(self, issuer, sequence, name):
        short_text(name, 48)
        if not name.strip():raise ValueError('LOCAL_CUSTODY_GUILD_NAME')
        def apply(payloads, shared):
            if any(issuer in g['members'] or name.casefold() == g['name'].casefold() for g in shared['guilds'].values()):
                raise ValueError('LOCAL_CUSTODY_GUILD_MEMBERSHIP')
            self._money(payloads[issuer], -10000);shared['money_sinks'] += 10000
            key = issuer + ':' + str(sequence)
            shared['guilds'][key] = guild_record(name,leader=issuer)
            shared['guilds'][key]['leader']=issuer
            return dict(guild=key)
        return self.transact(issuer, sequence, dict(op='GUILD_CREATE', name=name), [issuer], apply)

    def invite_guild_member(self, issuer, sequence, guild_id, member, *, now=None):
        identity(member)
        moment = clock(time.time() if now is None else now)
        def apply(payloads, shared):
            shared['clock'] = max(shared['clock'], moment)
            guild = shared['guilds'].get(guild_id)
            member_record=guild.get('members',{}).get(issuer) if guild else None
            if not member_record or not guild['ranks'][member_record['rank']]['rights']&16:
                raise ValueError('LOCAL_CUSTODY_GUILD_PERMISSION')
            if member in guild['members']:raise ValueError('LOCAL_CUSTODY_GUILD_MEMBERSHIP')
            if member in shared['guild_invites'] and shared['guild_invites'][member]['expires'] > shared['clock']:
                raise ValueError('LOCAL_CUSTODY_GUILD_INVITATION_PENDING')
            shared['guild_invites'][member] = dict(guild=guild_id, leader=guild['leader'],inviter=issuer,expires=shared['clock']+60)
            return dict(guild=guild_id, member=member)
        return self.transact(issuer, sequence, dict(op='GUILD_INVITE', guild=guild_id, member=member), [], apply)

    def answer_guild_invite(self, issuer, sequence, accept, *, now=None):
        if type(accept) is not bool:raise ValueError('LOCAL_CUSTODY_BOOLEAN_INVALID')
        moment = clock(time.time() if now is None else now)
        def apply(payloads, shared):
            shared['clock'] = max(shared['clock'], moment)
            offer = shared['guild_invites'].get(issuer)
            if not offer or offer['expires'] <= shared['clock']:raise ValueError('LOCAL_CUSTODY_GUILD_INVITATION_EXPIRED')
            if accept:shared['guilds'][offer['guild']]['members'][issuer] = dict(rank=4,note='',officer_note='')
            del shared['guild_invites'][issuer]
            return dict(guild=offer['guild'], accepted=accept)
        return self.transact(issuer, sequence, dict(op='GUILD_ANSWER', accept=accept), [], apply)

    def guild_action(self,issuer,sequence,guild_id,row):
        allowed=('GuildUninvite','GuildPromote','GuildDemote','GuildLeader','GuildMotd','GuildInfoText',
                 'GuildPublicNote','GuildOfficerNote','GuildSaveRank','GuildAddRank','GuildDelRank',
                 'GuildSelect','GuildShowOffline','GuildSort','GuildDisband','GuildLeave')
        if not isinstance(row,dict) or row.get('op') not in allowed:raise ValueError('LOCAL_CUSTODY_GUILD_ACTION')
        def apply(payloads,shared):
            stored=shared['guilds'].get(guild_id)
            if not stored or issuer not in stored['members']:raise ValueError('GUILD_MEMBERSHIP_REQUIRED')
            if row['op']=='GuildLeave':
                if stored['leader']==issuer and len(stored['members'])>1:raise ValueError('GUILD_TRANSFER_LEADERSHIP_FIRST')
                del stored['members'][issuer]
                if not stored['members']:del shared['guilds'][guild_id]
                result=[{'event':'GUILD_ROSTER_UPDATE','args':[]},{'event':'PLAYER_GUILD_UPDATE','args':['player']}]
            else:
                # Reuse the existing permission/rank algorithm on this actual
                # guild record, translating only the current client alias.
                aliased=copy.deepcopy(stored)
                aliased['members']['player']=aliased['members'].pop(issuer)
                class GuildContext(SocialServicesMixin):
                    def _service_person_locked(self,value,**kwargs):return 'player' if value==issuer else value
                context=GuildContext();context._services={'guild':aliased}
                result=context._guild_command_locked(copy.deepcopy(row))
                updated=context._services['guild']
                if updated:
                    updated['members'][issuer]=updated['members'].pop('player')
                    updated['leader']=next(k for k,m in updated['members'].items() if m['rank']==0)
                    shared['guilds'][guild_id]=updated
                else:del shared['guilds'][guild_id]
            for member,invite in list(shared['guild_invites'].items()):
                guild=shared['guilds'].get(invite['guild'])
                if not guild or invite['inviter'] not in guild['members'] or invite['leader']!=guild['leader']:
                    del shared['guild_invites'][member]
            return dict(guild=guild_id,events=result)
        return self.transact(issuer,sequence,dict(op='GUILD_ACTION',guild=guild_id,row=copy.deepcopy(row)),[],apply)

    def mail_action(self, issuer, sequence, mail_id, action, *, now=None):
        if action not in ('READ','DELETE','RETURN'):raise ValueError('LOCAL_CUSTODY_MAIL_ACTION')
        moment = clock(time.time() if now is None else now)
        def apply(payloads, shared):
            shared['clock'] = max(shared['clock'], moment)
            mail = shared['mail'].get(mail_id)
            if not mail or mail['recipient'] != issuer:raise ValueError('LOCAL_CUSTODY_MAIL_CHANGED')
            if action == 'READ':mail['read'] = True
            elif action == 'DELETE':
                if mail['asset'] or mail['money']:raise ValueError('LOCAL_CUSTODY_MAIL_ASSETS_UNCOLLECTED')
                del shared['mail'][mail_id]
            else:
                if mail['returned'] or mail['system']:raise ValueError('LOCAL_CUSTODY_MAIL_CANNOT_RETURN')
                self._return_mail(shared, mail)
            return dict(mail=mail_id, action=action)
        return self.transact(issuer, sequence, dict(op='MAIL_ACTION', mail=mail_id, action=action), [], apply)

    def save_mail_text(self,issuer,sequence,mail_id,*,catalog):
        definition=items.definition(catalog,'item.gg_letter')
        if not definition or 'NO_TRADE' not in definition.get('tags',[]):raise ValueError('LOCAL_CUSTODY_LETTER_DEFINITION')
        def apply(payloads,shared):
            mail=shared['mail'].get(mail_id)
            if not mail or mail['recipient']!=issuer or mail['permanent'] or not mail['body']:
                raise ValueError('LOCAL_CUSTODY_LETTER_ENTITLEMENT')
            payload=payloads[issuer];rows=payload['item_instances']
            inventory=[i for i in rows if i['owner_id']=='player' and i['location']=='INVENTORY']
            if len(rows)>=items.MAX_WORLD_INSTANCES or len(inventory)>=items.MAX_INVENTORY_SLOTS:
                raise ValueError('LOCAL_CUSTODY_INVENTORY_FULL')
            key='letter-'+digest(dict(recipient=issuer,mail=mail_id))[:32]
            if any(i['instance_id']==key for i in rows):raise ValueError('LOCAL_CUSTODY_ITEM_ID_COLLISION')
            letter=items.make_instance(catalog,key,'item.gg_letter')
            used={i.get('slot_index') for i in inventory}
            letter['slot_index']=min(set(range(items.MAX_INVENTORY_SLOTS))-used)
            letter['letter']=dict(subject=mail['subject'],body=mail['body'],sender=mail['sender'])
            rows.append(letter);self._sync_inventory(payload);mail['permanent']=True
            return dict(mail=mail_id,item=key)
        return self.transact(issuer,sequence,dict(op='MAIL_TEXT',mail=mail_id),[issuer],apply,_letter_source=mail_id)

    @staticmethod
    def _return_mail(shared, mail):
        mail['sender'], mail['recipient'] = mail['recipient'], mail['sender']
        mail.update(returned=True, read=False, cod=0, expires=shared['clock'] + 30 * 86400)
        if mail['asset']:shared['escrow'][mail['asset']]['owner_id'] = mail['recipient']

    @staticmethod
    def _group_for(shared,member):
        return next(((key,group) for key,group in shared.get('groups',{}).items() if member in group['members']),(None,None))

    @staticmethod
    def _prune_groups(shared):
        shared_channels.prune(shared)
        groups=shared.setdefault('groups',{});invites=shared.setdefault('group_invites',{})
        for member,offer in list(invites.items()):
            group=groups.get(offer['group'])
            if not group or not group['members'] or group['leader'] not in group['members'] or offer['leader']!=group['leader'] or offer['expires']<=shared['clock']:
                del invites[member]
        for key,group in list(groups.items()):
            if len(group['members'])<2 and not any(offer['group']==key for offer in invites.values()):
                del groups[key]
            elif group['ready'] and not group['ready']['finished'] and group['ready']['expires']<=shared['clock']:
                group['ready']['finished']=True

    def group_action(self,issuer,sequence,row,*,now=None):
        """Consent and administration over actual saved identities, never NPC bodies."""
        allowed=('GroupInvite','GroupAccept','GroupDecline','GroupLeave','GroupKick','GroupLeader',
                 'GroupRaid','GroupAssistant','GroupSubgroup','GroupSwap','GroupLoot','GroupThreshold',
                 'GroupMark','GroupReady','GroupReadyAnswer')
        if not isinstance(row,dict) or row.get('op') not in allowed:raise ValueError('GROUP_COMMAND_UNKNOWN')
        request=copy.deepcopy(row);op=request['op'];moment=clock(time.time() if now is None else now)
        def apply(payloads,shared):
            shared['clock']=max(shared['clock'],moment);self._prune_groups(shared)
            groups=shared['groups'];invites=shared['group_invites'];key,group=self._group_for(shared,issuer)
            members=group['members'] if group else []
            def target(field='target'):
                value=request.get(field);identity(value)
                if value not in self._roster():raise ValueError('SERVICE_PERSON_UNKNOWN')
                return value
            def leader():
                if not group or group['leader']!=issuer:raise ValueError('GROUP_LEADER_REQUIRED')
            if op=='GroupInvite':
                member=target()
                if member==issuer or self._group_for(shared,member)[1]:raise ValueError('GROUP_ALREADY_MEMBER')
                sender_name=next(r['name'] for r in self._read('characters.json',MAX_BYTES)['characters'] if r['id']==issuer)
                ignored=self._character(member)['payload'].get('player',{}).get('client_controls',{}).get('local_client',{}).get('ignores',[])
                if any(isinstance(name,str) and name.casefold()==sender_name.casefold() for name in ignored):raise ValueError('GROUP_TARGET_IGNORES_PLAYER')
                if member in invites:raise ValueError('GROUP_INVITATION_PENDING')
                if issuer in invites:raise ValueError('GROUP_INVITATION_PENDING')
                if not group:
                    key='group-'+digest(dict(issuer=issuer,sequence=sequence))[:32]
                    group=dict(members=[issuer],raid=False,leader=issuer,assistants=[],subgroups={issuer:1},
                               loot_method='freeforall',threshold=2,master=issuer,marks={},ready={})
                    groups[key]=group;members=group['members']
                leader()
                if len(members)>=(40 if group['raid'] else 5):raise ValueError('GROUP_FULL')
                invites[member]=dict(group=key,leader=issuer,inviter=issuer,expires=shared['clock']+GROUP_INVITE_SECONDS)
            elif op in ('GroupAccept','GroupDecline'):
                offer=invites.get(issuer)
                if not offer:raise ValueError('GROUP_INVITATION_EXPIRED')
                key=offer['group'];group=groups[key]
                if op=='GroupAccept':
                    if self._group_for(shared,issuer)[1]:raise ValueError('GROUP_ALREADY_MEMBER')
                    if len(group['members'])>=(40 if group['raid'] else 5):raise ValueError('GROUP_FULL')
                    subgroup=next((i for i in range(1,9) if sum(v==i for v in group['subgroups'].values())<5),None)
                    if subgroup is None:raise ValueError('GROUP_FULL')
                    group['members'].append(issuer);group['subgroups'][issuer]=subgroup;group['ready']={}
                del invites[issuer]
            else:
                if not group:raise ValueError('GROUP_REQUIRED')
                if op not in ('GroupLeave','GroupMark','GroupReadyAnswer'):leader()
                if op in ('GroupLeave','GroupKick'):
                    member=issuer if op=='GroupLeave' else target()
                    if member not in members or op=='GroupKick' and member==issuer:raise ValueError('GROUP_MEMBER_CHANGED')
                    members.remove(member);group['subgroups'].pop(member);group['marks'].pop(member,None)
                    group['assistants']=[m for m in group['assistants'] if m!=member];group['ready']={}
                    if group['leader']==member and members:group['leader']=members[0]
                    if group['master']==member and members:group['master']=group['leader']
                    group['assistants']=[m for m in group['assistants'] if m!=group['leader']]
                elif op=='GroupLeader':
                    member=target()
                    if member not in members:raise ValueError('GROUP_MEMBER_CHANGED')
                    group['leader']=member;group['assistants']=[m for m in group['assistants'] if m!=member]
                elif op=='GroupRaid':
                    if len(members)<2:raise ValueError('GROUP_REQUIRED')
                    group['raid']=True
                elif op=='GroupAssistant':
                    member=target()
                    if not group['raid']:raise ValueError('GROUP_RAID_REQUIRED')
                    if member not in members or member==group['leader']:raise ValueError('GROUP_MEMBER_CHANGED')
                    if type(request.get('grant')) is not bool:raise ValueError('GROUP_BOOLEAN_REQUIRED')
                    if request['grant'] and member not in group['assistants']:group['assistants'].append(member)
                    elif not request['grant'] and member in group['assistants']:group['assistants'].remove(member)
                elif op in ('GroupSubgroup','GroupSwap'):
                    if not group['raid']:raise ValueError('GROUP_RAID_REQUIRED')
                    member=target()
                    if member not in members:raise ValueError('GROUP_MEMBER_CHANGED')
                    if op=='GroupSwap':
                        other=target('other_target')
                        if other not in members:raise ValueError('GROUP_MEMBER_CHANGED')
                        group['subgroups'][member],group['subgroups'][other]=group['subgroups'][other],group['subgroups'][member]
                    else:
                        subgroup=integer(request.get('subgroup'),1,8)
                        if sum(v==subgroup for m,v in group['subgroups'].items() if m!=member)>=5:raise ValueError('GROUP_SUBGROUP_FULL')
                        group['subgroups'][member]=subgroup
                elif op in ('GroupLoot','GroupThreshold'):
                    if op=='GroupLoot':
                        method=request.get('method')
                        if method not in LOOT_METHODS:raise ValueError('GROUP_LOOT_METHOD_INVALID')
                        master=target('master') if request.get('master') else issuer
                        if master not in members:raise ValueError('GROUP_MASTER_NOT_MEMBER')
                        group.update(loot_method=method,master=master)
                    threshold=request.get('threshold')
                    group['threshold']=integer(group['threshold'] if threshold is None and op=='GroupLoot' else threshold,2,4)
                elif op=='GroupMark':
                    member=target()
                    if member not in members:raise ValueError('GROUP_MEMBER_CHANGED')
                    index=integer(request.get('index'),0,8)
                    for marked in list(group['marks']):
                        if index and group['marks'][marked]==index:del group['marks'][marked]
                    group['marks'][member]=index
                elif op=='GroupReady':
                    if len(members)<2:raise ValueError('GROUP_REQUIRED')
                    group['ready']=dict(id='ready-'+digest(dict(issuer=issuer,sequence=sequence))[:32],initiator=issuer,
                        expires=shared['clock']+GROUP_READY_SECONDS,answers={m:True if m==issuer else None for m in members},finished=False)
                elif op=='GroupReadyAnswer':
                    ready=group['ready']
                    if not ready or ready['finished']:raise ValueError('GROUP_NO_READY_CHECK')
                    if type(request.get('ready')) is not bool:raise ValueError('GROUP_BOOLEAN_REQUIRED')
                    if ready['answers'][issuer] is not None:raise ValueError('GROUP_READY_ALREADY_ANSWERED')
                    ready['answers'][issuer]=request['ready']
                    ready['finished']=all(value is not None for value in ready['answers'].values())
            self._prune_groups(shared)
            return dict(group=key,operation=op)
        return self.transact(issuer,sequence,dict(op='GROUP_ACTION',row=request),[],apply)

    def settle(self, issuer, sequence, *, now):
        moment = clock(now)
        def apply(payloads, shared):
            shared['clock'] = max(shared['clock'], moment)
            for key in sorted(list(shared['auctions'])):
                if shared['auctions'][key]['expires'] <= shared['clock']:
                    self._finish_auction(shared, key, issuer + ':' + str(sequence) + ':' + digest(key)[:16])
            for mail in shared['mail'].values():
                if mail['expires'] <= shared['clock'] and not mail['returned'] and not mail['system']:
                    self._return_mail(shared, mail)
            for member in list(shared['guild_invites']):
                if shared['guild_invites'][member]['expires'] <= shared['clock']:del shared['guild_invites'][member]
            self._prune_groups(shared)
            petitions.prune(shared)
            direct_trades.prune(shared)
            for member,inbox in list(shared.get('chat',{}).items()):
                remaining=[message for message in inbox if message.get('expires',MAX_CLOCK)>shared['clock']]
                if remaining:shared['chat'][member]=remaining
                else:del shared['chat'][member]
            return dict(clock=shared['clock'])
        return self.transact(issuer, sequence, dict(op='SETTLE', now=moment), [], apply)

    def send_chat(self,issuer,sequence,kind,message,*,recipient='',now=None,expected_revision=None,prefix='',distribution=''):
        """Deliver bounded messages only to real saved local characters."""
        if kind not in ('GUILD','OFFICER','WHISPER','PARTY','RAID','ADDON'):raise ValueError('LOCAL_CUSTODY_CHAT_INVALID')
        if kind=='ADDON':
            addon_payload(prefix,message,distribution)
        else:
            short_text(message,255)
            if not message.strip() or prefix or distribution:raise ValueError('LOCAL_CUSTODY_CHAT_INVALID')
        if kind!='ADDON':message=message.strip()
        if kind=='WHISPER':identity(recipient)
        elif recipient:raise ValueError('LOCAL_CUSTODY_CHAT_INVALID')
        moment=clock(time.time() if now is None else now)
        def apply(payloads,shared):
            shared['clock']=max(shared['clock'],moment)
            if kind=='WHISPER':
                if recipient==issuer or recipient not in self._roster():raise ValueError('LOCAL_CUSTODY_RECIPIENT_UNAVAILABLE')
                recipients=[recipient]
            elif kind in ('PARTY','RAID','ADDON'):
                _,group=self._group_for(shared,issuer)
                if not group or len(group['members'])<2:raise ValueError('CHAT_GROUP_REQUIRED')
                if (distribution if kind=='ADDON' else kind)=='RAID' and not group['raid']:raise ValueError('GROUP_RAID_REQUIRED')
                channel=distribution if kind=='ADDON' else kind
                recipients=[member for member in group['members'] if member!=issuer and
                    (channel=='RAID' or not group['raid'] or group['subgroups'][member]==group['subgroups'][issuer])]
            else:
                guild=next((g for g in shared['guilds'].values() if issuer in g['members']),None)
                if not guild or not guild['ranks'][guild['members'][issuer]['rank']]['rights'] & (8 if kind=='OFFICER' else 2):
                    raise ValueError('GUILD_PERMISSION_DENIED')
                recipients=[key for key,member in guild['members'].items() if key!=issuer and
                            guild['ranks'][member['rank']]['rights'] & (4 if kind=='OFFICER' else 1)]
            inboxes=shared.setdefault('chat',{})
            sender_name=next(r['name'] for r in self._read('characters.json',MAX_BYTES)['characters'] if r['id']==issuer)
            delivered=[]
            for target in recipients:
                controls=self._character(target)['payload'].get('player',{}).get('client_controls',{}).get('local_client',{})
                if any(isinstance(n,str) and n.casefold()==sender_name.casefold() for n in controls.get('ignores',[])):continue
                inbox=inboxes.setdefault(target,[])
                if len(inbox)>=MAX_CHAT_INBOX:raise ValueError('LOCAL_CUSTODY_CHAT_INBOX_FULL')
                key='chat-'+digest(dict(sender=issuer,sequence=sequence,recipient=target))[:32]
                message_row=dict(id=key,sender=issuer,recipient=target,kind=kind,text=message,sent=shared['clock'])
                if kind in ('PARTY','RAID','ADDON'):message_row['expires']=shared['clock']+GROUP_CHAT_SECONDS
                if kind=='ADDON':message_row.update(prefix=prefix,distribution=distribution)
                inbox.append(message_row)
                delivered.append(target)
            return dict(recipients=delivered,text=message,kind=kind)
        request=dict(op='CHAT_SEND',kind=kind,text=message,recipient=recipient)
        if kind=='ADDON':request.update(prefix=prefix,distribution=distribution)
        return self.transact(issuer,sequence,request,[issuer],apply,
                             expected_revisions={} if expected_revision is None else {issuer:expected_revision})

    def acknowledge_chat(self,issuer,sequence,message_ids):
        """Remove only the active recipient's successfully published message IDs."""
        if not isinstance(message_ids,list) or not 1<=len(message_ids)<=MAX_CHAT_INBOX:
            raise ValueError('LOCAL_CUSTODY_CHAT_ACK_INVALID')
        for key in message_ids:
            if not isinstance(key,str) or len(key)!=37 or not key.startswith('chat-') or any(c not in '0123456789abcdef' for c in key[5:]):
                raise ValueError('LOCAL_CUSTODY_CHAT_ACK_INVALID')
        if len(set(message_ids))!=len(message_ids):raise ValueError('LOCAL_CUSTODY_CHAT_ACK_INVALID')
        frozen=sorted(message_ids)
        def apply(payloads,shared):
            inboxes=shared.setdefault('chat',{})
            inbox=inboxes.get(issuer,[])
            actual={m['id'] for m in inbox}
            if set(frozen)-actual:raise ValueError('LOCAL_CUSTODY_CHAT_MESSAGE_CHANGED')
            remaining=[m for m in inbox if m['id'] not in frozen]
            if remaining:inboxes[issuer]=remaining
            else:inboxes.pop(issuer,None)
            return dict(acknowledged=frozen)
        return self.transact(issuer,sequence,dict(op='CHAT_ACK',ids=frozen),[],apply)
