"""Explicit saved-character custom channels, without offline world actors.

The original five GG Island zone channels remain the physical NPC path.  This
optional account ledger is for custom rooms explicitly selected as shared.
Membership has no invented expiry; asynchronous invitations last sixty seconds
and queued chat lasts thirty days, the same declared GG delivery policy as
saved-character party chat.  Passwords use the existing bounded scrypt format;
neither plaintext passwords nor password arguments enter a durable receipt.
"""
from __future__ import annotations
from backend.platform_files import secure_open, NOFOLLOW, CLOEXEC, NONBLOCK, sync_directory

import copy
from backend.platform_support import file_locks as fcntl
import hashlib
import os
import time
from contextlib import contextmanager

from backend.game_engine_adapter_channels import ZONE_CHANNELS, password_record, password_matches

MAX_CHANNELS = 32
MAX_SLOTS = 10
INVITE_SECONDS = 60
MESSAGE_SECONDS = 30 * 86400
ROOM_FIELDS = {'name', 'owner', 'members', 'slots', 'moderators', 'muted', 'banned',
               'moderated', 'announcements', 'password', 'revision'}
NOTICE_CODES = {'JOINED', 'LEFT', 'YOU_JOINED', 'YOU_LEFT', 'PASSWORD_CHANGED',
                'OWNER_CHANGED', 'MODE_CHANGE', 'ANNOUNCEMENTS_ON', 'ANNOUNCEMENTS_OFF',
                'MODERATION_ON', 'MODERATION_OFF', 'PLAYER_KICKED', 'PLAYER_BANNED',
                'PLAYER_UNBANNED', 'INVITE', 'PLAYER_INVITED'}
TARGET_OPS = {'ChannelInvite', 'ChannelKick', 'ChannelBan', 'ChannelUnban',
              'ChannelSetOwner', 'ChannelModerator', 'ChannelUnmoderator',
              'ChannelMute', 'ChannelUnmute'}
OWNER_OPS = {'ChannelSetOwner', 'ChannelSetPassword', 'ChannelModerator',
             'ChannelUnmoderator', 'ChannelModerate'}
MANAGE_OPS = TARGET_OPS | OWNER_OPS | {'ChannelToggleAnnouncements'}
ACTION_OPS = MANAGE_OPS | {'ChannelJoin', 'ChannelLeave', 'ChannelMessage'}


def _custody():
    from backend import game_engine_local_custody
    return game_engine_local_custody


def channel_name(value):
    c = _custody(); c.short_text(value, 80)
    if (not value or value != value.strip() or value.isdecimal() or
            any(value.casefold() in (name.casefold(), (name + ' - GG Island').casefold())
                for name in ZONE_CHANNELS)):
        raise ValueError('CHANNEL_CUSTOM_NAME_REQUIRED')
    return value


def channel_id(name):
    return 'channel-' + _custody().digest(channel_name(name).casefold())[:32]


def _password(value):
    if value is None:
        return
    if (not isinstance(value, dict) or set(value) != {'salt', 'digest'} or
            not isinstance(value['salt'], str) or len(value['salt']) != 32 or
            not isinstance(value['digest'], str) or len(value['digest']) != 128 or
            any(ch not in '0123456789abcdef' for ch in value['salt'] + value['digest'])):
        raise ValueError('CHANNEL_PASSWORD_RECORD_INVALID')


def _npc_slots(envelope):
    slots = envelope['payload'].get('player', {}).get('client_controls', {}).get(
        'services', {}).get('channel_slots', [None] * MAX_SLOTS)
    if not isinstance(slots, list) or len(slots) != MAX_SLOTS:
        raise ValueError('CHANNEL_SLOTS_INVALID')
    return slots


def validate(characters, shared):
    c = _custody(); rooms = shared.get('shared_channels', {})
    offers = shared.get('channel_invites', {})
    if not isinstance(rooms, dict) or len(rooms) > MAX_CHANNELS:
        raise ValueError('CHANNEL_CAPACITY')
    if not isinstance(offers, dict) or len(offers) > MAX_SLOTS:
        raise ValueError('CHANNEL_INVITE_CAPACITY')
    occupied = {key: set() for key in characters}
    for key, room in rooms.items():
        if not isinstance(room, dict) or set(room) != ROOM_FIELDS or channel_id(room['name']) != key:
            raise ValueError('CHANNEL_RECORD_INVALID')
        c.integer(room['revision'], 1, c.MAX_SEQUENCE)
        if any(type(room[field]) is not bool for field in ('moderated', 'announcements')):
            raise ValueError('CHANNEL_FLAGS_INVALID')
        _password(room['password'])
        for field in ('members', 'moderators', 'muted', 'banned'):
            members = room[field]
            if (not isinstance(members, list) or len(members) > MAX_SLOTS or
                    any(not isinstance(member, str) or member not in characters for member in members) or
                    len(set(members)) != len(members)):
                raise ValueError('CHANNEL_MEMBERS_INVALID')
        members = set(room['members'])
        if (not isinstance(room['owner'], str) or bool(room['owner']) != bool(members) or
                room['owner'] and room['owner'] not in members or
                set(room['moderators']) - members or set(room['muted']) - members or
                members & set(room['banned']) or room['owner'] in room['muted']):
            raise ValueError('CHANNEL_OWNER_INVALID')
        slots = room['slots']
        if not isinstance(slots, dict) or set(slots) != members:
            raise ValueError('CHANNEL_SLOTS_INVALID')
        for member, slot in slots.items():
            c.integer(slot, 1, MAX_SLOTS)
            if slot in occupied[member] or _npc_slots(characters[member])[slot - 1] is not None:
                raise ValueError('CHANNEL_JOIN_CAPACITY')
            occupied[member].add(slot)
    offer_ids = set()
    for recipient, offer in offers.items():
        if (recipient not in characters or not isinstance(offer, dict) or
                set(offer) != {'id', 'channel', 'sender', 'expires'} or
                offer['sender'] not in characters or recipient == offer['sender']):
            raise ValueError('CHANNEL_INVITE_INVALID')
        key = offer['id']
        if (not isinstance(key, str) or len(key) != 40 or not key.startswith('channel-') or
                any(ch not in '0123456789abcdef' for ch in key[8:]) or key in offer_ids):
            raise ValueError('CHANNEL_INVITE_INVALID')
        offer_ids.add(key)
        room = rooms.get(offer['channel'])
        if (not room or offer['sender'] not in room['members'] or
                not authority(room, offer['sender']) or recipient in room['members'] or
                recipient in room['banned']):
            raise ValueError('CHANNEL_INVITE_INVALID')
        c.clock(offer['expires'])
        if offer['expires'] > shared['clock'] + INVITE_SECONDS:
            raise ValueError('CHANNEL_INVITE_INVALID')


def authority(room, character):
    return room['owner'] == character or character in room['moderators']


def reserved_slots(shared, character):
    return {room['slots'][character] for room in shared.get('shared_channels', {}).values()
            if character in room['slots']}


def delete_blockers(character, shared):
    result = []
    if any(character == room['owner'] or any(character in room[field] for field in
           ('members', 'moderators', 'muted', 'banned')) for room in shared.get('shared_channels', {}).values()):
        result.append('CHANNEL_MEMBERSHIP')
    if character in shared.get('channel_invites', {}) or any(
            offer['sender'] == character for offer in shared.get('channel_invites', {}).values()):
        result.append('CHANNEL_INVITE')
    return result


def prune(shared):
    rooms = shared.get('shared_channels', {})
    for recipient, offer in list(shared.get('channel_invites', {}).items()):
        room = rooms.get(offer['channel'])
        if (offer['expires'] <= shared['clock'] or not room or
                not authority(room, offer['sender']) or recipient in room['members'] or
                recipient in room['banned']):
            del shared['channel_invites'][recipient]


def validate_message(message, recipient, characters):
    c = _custody()
    fields = {'id', 'sender', 'recipient', 'kind', 'text', 'sent', 'expires',
              'channel_id', 'channel_name', 'channel_slot'}
    if message.get('kind') == 'CHANNEL_NOTICE':
        fields.add('notice')
    if set(message) != fields or message['kind'] not in ('CHANNEL', 'CHANNEL_NOTICE'):
        raise ValueError('LOCAL_CUSTODY_CHAT_INVALID')
    if (message['sender'] not in characters or message['recipient'] != recipient or
            message['sender'] == recipient):
        raise ValueError('LOCAL_CUSTODY_CHAT_INVALID')
    key = message['id']
    if (not isinstance(key, str) or len(key) != 37 or not key.startswith('chat-') or
            any(ch not in '0123456789abcdef' for ch in key[5:])):
        raise ValueError('LOCAL_CUSTODY_CHAT_INVALID')
    if channel_id(message['channel_name']) != message['channel_id']:
        raise ValueError('LOCAL_CUSTODY_CHAT_INVALID')
    c.integer(message['channel_slot'], 0, MAX_SLOTS)
    c.clock(message['sent']); c.clock(message['expires']); c.short_text(message['text'], 255)
    if message['kind'] == 'CHANNEL':
        if not message['text'].strip() or not message['channel_slot']:
            raise ValueError('LOCAL_CUSTODY_CHAT_INVALID')
    elif message['notice'] not in NOTICE_CODES or message['text']:
        raise ValueError('LOCAL_CUSTODY_CHAT_INVALID')
    duration = INVITE_SECONDS if message.get('notice') == 'INVITE' else MESSAGE_SECONDS
    if message['expires'] != message['sent'] + duration:
        raise ValueError('LOCAL_CUSTODY_CHAT_INVALID')


def _ignored(characters, target, sender, names):
    client = characters[target]['payload'].get('player', {}).get('client_controls', {}).get('local_client', {})
    return any(isinstance(name, str) and name.casefold() == names[sender].casefold()
               for name in client.get('ignores', []))


def _queue(characters, shared, issuer, sequence, room_id, room, recipients, *, names,
           kind='CHANNEL_NOTICE', text='', notice='', slots=None, ignore=False, index=0):
    c = _custody(); delivered = []
    for target in recipients:
        if target == issuer or ignore and _ignored(characters, target, issuer, names):
            continue
        inbox = shared.setdefault('chat', {}).setdefault(target, [])
        if len(inbox) >= c.MAX_CHAT_INBOX:
            raise ValueError('LOCAL_CUSTODY_CHAT_INBOX_FULL')
        slot = (slots if slots is not None else room['slots']).get(target, 0)
        key = 'chat-' + c.digest(dict(sender=issuer, sequence=sequence, recipient=target,
                                     channel=room_id, notice=notice, index=index))[:32]
        row = dict(id=key, sender=issuer, recipient=target, kind=kind, text=text,
                   sent=shared['clock'], expires=shared['clock'] + (
                       INVITE_SECONDS if notice == 'INVITE' else MESSAGE_SECONDS),
                   channel_id=room_id, channel_name=room['name'], channel_slot=slot)
        if kind == 'CHANNEL_NOTICE':
            row['notice'] = notice
        inbox.append(row); delivered.append(target)
    return delivered


def apply(characters, shared, issuer, sequence, row, *, now, names):
    """Pure bounded transition over actual saved participants; no item mutation."""
    c = _custody(); c.identity(issuer); c.integer(sequence, 1, c.MAX_SEQUENCE)
    op = row.get('op')
    expected = {'op', 'name', 'id', 'revision'}
    if op in ('ChannelJoin', 'ChannelSetPassword'):
        expected.add('password_proof')
    if op in TARGET_OPS:
        expected.add('target')
    if op == 'ChannelMessage':
        expected.add('text')
    if op not in ACTION_OPS or set(row) != expected or issuer not in characters:
        raise ValueError('CHANNEL_COMMAND_INVALID')
    name = channel_name(row['name']); key = channel_id(name)
    if row['id'] != key:
        raise ValueError('CHANNEL_CHANGED')
    if row['revision'] is not None:
        c.integer(row['revision'], 1, c.MAX_SEQUENCE)
    if 'password_proof' in row:
        _password(row['password_proof'])
    shared['clock'] = max(shared['clock'], c.clock(now)); prune(shared)
    rooms = shared.setdefault('shared_channels', {}); room = rooms.get(key)
    if row['revision'] is not None and (not room or room['revision'] != row['revision']):
        raise ValueError('CHANNEL_CHANGED')
    slot = room['slots'].get(issuer, 0) if room else 0
    own_notice = ''; delivered = []
    if op == 'ChannelJoin':
        if room and issuer in room['members']:
            return dict(channel=key, slot=slot, notice='', recipients=[])
        occupied = reserved_slots(shared, issuer)
        free = [index + 1 for index, value in enumerate(_npc_slots(characters[issuer]))
                if value is None and index + 1 not in occupied]
        if not free:
            raise ValueError('CHANNEL_JOIN_CAPACITY')
        if room:
            if issuer in room['banned']:
                raise ValueError('CHANNEL_BANNED')
            if room['password'] is not None and row['password_proof'] != room['password']:
                raise ValueError('CHANNEL_PASSWORD_INVALID')
            if len(room['members']) >= MAX_SLOTS:
                raise ValueError('CHANNEL_MEMBER_CAPACITY')
        else:
            if len(rooms) >= MAX_CHANNELS:
                raise ValueError('CHANNEL_CAPACITY')
            room = dict(name=name, owner=issuer, members=[], slots={}, moderators=[],
                        muted=[], banned=[], moderated=False, announcements=True,
                        password=copy.deepcopy(row['password_proof']), revision=1)
            rooms[key] = room
        room['members'].append(issuer); room['slots'][issuer] = slot = free[0]
        if not room['owner']:
            room['owner'] = issuer
        offers = shared.setdefault('channel_invites', {})
        if issuer in offers and offers[issuer]['channel'] == key:
            del offers[issuer]
            inbox = shared.get('chat', {}).get(issuer, [])
            remaining = [m for m in inbox if not (m.get('kind') == 'CHANNEL_NOTICE' and
                         m.get('notice') == 'INVITE' and m.get('channel_id') == key)]
            if remaining:
                shared['chat'][issuer] = remaining
            else:
                shared.get('chat', {}).pop(issuer, None)
        if room['announcements']:
            delivered = _queue(characters, shared, issuer, sequence, key, room,
                               room['members'], names=names, notice='JOINED')
        own_notice = 'YOU_JOINED'
    else:
        if not room or issuer not in room['members']:
            raise ValueError('CHANNEL_NOT_JOINED')
        if op == 'ChannelMessage':
            c.short_text(row['text'], 255)
            if not row['text'].strip():
                raise ValueError('LOCAL_CUSTODY_CHAT_INVALID')
            if issuer in room['muted'] or room['moderated'] and not authority(room, issuer):
                raise ValueError('CHANNEL_MUTED')
            delivered = _queue(characters, shared, issuer, sequence, key, room,
                               room['members'], names=names, kind='CHANNEL',
                               text=row['text'].strip(), ignore=True)
            return dict(channel=key, slot=slot, notice='', recipients=delivered,
                        text=row['text'].strip())
        if op == 'ChannelLeave':
            old_slots = dict(room['slots']); room['members'].remove(issuer); del room['slots'][issuer]
            for field in ('moderators', 'muted'):
                if issuer in room[field]:
                    room[field].remove(issuer)
            if room['announcements']:
                delivered = _queue(characters, shared, issuer, sequence, key, room,
                                   room['members'], names=names, notice='LEFT', slots=old_slots)
            if room['owner'] == issuer:
                room['owner'] = next(iter(room['members']), '')
                if room['owner'] in room['muted']:
                    room['muted'].remove(room['owner'])
                if room['members']:
                    _queue(characters, shared, issuer, sequence, key, room,
                           room['members'], names=names, notice='OWNER_CHANGED', index=1)
            own_notice = 'YOU_LEFT'
        else:
            if not authority(room, issuer):
                raise ValueError('CHANNEL_MODERATOR_REQUIRED')
            if op in OWNER_OPS and room['owner'] != issuer:
                raise ValueError('CHANNEL_OWNER_REQUIRED')
            target = row.get('target')
            if op in TARGET_OPS:
                c.identity(target)
                if target not in characters:
                    raise ValueError('CHANNEL_PLAYER_NOT_FOUND')
            if op == 'ChannelInvite':
                if target in room['members']:
                    raise ValueError('CHANNEL_ALREADY_MEMBER')
                if target in room['banned']:
                    raise ValueError('CHANNEL_BANNED')
                if _ignored(characters, target, issuer, names):
                    raise ValueError('CHANNEL_INVITE_IGNORED')
                offers = shared.setdefault('channel_invites', {})
                if target in offers:
                    raise ValueError('CHANNEL_INVITE_PENDING')
                offers[target] = dict(id='channel-' + c.digest(dict(issuer=issuer, sequence=sequence,
                    recipient=target))[:32], channel=key, sender=issuer,
                    expires=shared['clock'] + INVITE_SECONDS)
                delivered = _queue(characters, shared, issuer, sequence, key, room,
                                   [target], names=names, notice='INVITE')
                own_notice = 'PLAYER_INVITED'
            elif op in ('ChannelKick', 'ChannelBan'):
                if target == room['owner']:
                    raise ValueError('CHANNEL_OWNER_PROTECTED')
                if target not in room['members']:
                    raise ValueError('CHANNEL_MEMBER_NOT_FOUND')
                old_slots = dict(room['slots']); room['members'].remove(target); del room['slots'][target]
                for field in ('moderators', 'muted'):
                    if target in room[field]:
                        room[field].remove(target)
                if op == 'ChannelBan':
                    room['banned'].append(target)
                own_notice = 'PLAYER_BANNED' if op == 'ChannelBan' else 'PLAYER_KICKED'
                delivered = _queue(characters, shared, issuer, sequence, key, room,
                                   list(room['members']) + [target], names=names,
                                   notice=own_notice, slots=old_slots)
            elif op == 'ChannelUnban':
                if target not in room['banned']:
                    raise ValueError('CHANNEL_NOT_BANNED')
                room['banned'].remove(target); own_notice = 'PLAYER_UNBANNED'
                delivered = _queue(characters, shared, issuer, sequence, key, room,
                                   room['members'], names=names, notice=own_notice)
            elif op == 'ChannelSetPassword':
                room['password'] = copy.deepcopy(row['password_proof']); own_notice = 'PASSWORD_CHANGED'
            elif op in ('ChannelModerate', 'ChannelToggleAnnouncements'):
                field = 'moderated' if op == 'ChannelModerate' else 'announcements'
                room[field] = not room[field]
                own_notice = ('MODERATION_' if field == 'moderated' else 'ANNOUNCEMENTS_') + (
                    'ON' if room[field] else 'OFF')
            else:
                if target not in room['members']:
                    raise ValueError('CHANNEL_MEMBER_NOT_FOUND')
                if op == 'ChannelSetOwner':
                    room['owner'] = target
                    if target in room['muted']:
                        room['muted'].remove(target)
                    own_notice = 'OWNER_CHANGED'
                else:
                    if target == room['owner']:
                        raise ValueError('CHANNEL_OWNER_PROTECTED')
                    field = 'moderators' if op in ('ChannelModerator', 'ChannelUnmoderator') else 'muted'
                    add = op in ('ChannelModerator', 'ChannelMute')
                    if add and target not in room[field]:
                        room[field].append(target)
                    elif not add and target in room[field]:
                        room[field].remove(target)
                    own_notice = 'MODE_CHANGE'
            if op not in ('ChannelInvite', 'ChannelKick', 'ChannelBan', 'ChannelUnban'):
                delivered = _queue(characters, shared, issuer, sequence, key, room,
                                   room['members'], names=names, notice=own_notice)
    room['revision'] = c.integer(room['revision'], 1, c.MAX_SEQUENCE - 1) + 1
    prune(shared)
    return dict(channel=key, slot=slot, notice=own_notice, recipients=delivered)


def _proof(password, record):
    if not isinstance(password, str) or len(password) > 128:
        raise ValueError('CHANNEL_PASSWORD_INVALID')
    if record is None:
        return None
    _password(record)
    value = hashlib.scrypt(password.encode(), salt=bytes.fromhex(record['salt']), n=4096, r=8, p=1).hex()
    return dict(salt=record['salt'], digest=value)


def canonical_request(row, shared, issuer, sequence):
    c = _custody(); op = row.get('op')
    if op not in ACTION_OPS:
        raise ValueError('CHANNEL_COMMAND_INVALID')
    name = channel_name(row.get('name')); key = channel_id(name)
    if row.get('channel_id', key) != key:
        raise ValueError('CHANNEL_CHANGED')
    room = shared.get('shared_channels', {}).get(key)
    prior = shared['receipts'].get(issuer + ':' + str(sequence))
    previous = prior['request'].get('row', {}) if prior and prior['request'].get('op') == 'CHANNEL_ACTION' else {}
    request = dict(op=op, name=name, id=key,
                   revision=row.get('channel_revision', previous.get('revision', room['revision'] if room else None)))
    if op in TARGET_OPS:
        request['target'] = row.get('target')
    if op == 'ChannelMessage':
        request['text'] = row.get('text')
    if op in ('ChannelJoin', 'ChannelSetPassword'):
        password = row.get('password', '')
        if not isinstance(password, str) or len(password) > 128:
            raise ValueError('CHANNEL_PASSWORD_INVALID')
        if previous.get('op') == op and previous.get('id') == key and 'password_proof' in previous:
            record = previous['password_proof']
            if (record is not None and not password_matches(password, record) or
                    record is None and op == 'ChannelSetPassword' and password):
                raise ValueError('LOCAL_CUSTODY_REPLAY_CHANGED')
            request['password_proof'] = copy.deepcopy(record)
        elif op == 'ChannelSetPassword' or not room:
            request['password_proof'] = password_record(password)
        else:
            request['password_proof'] = _proof(password, room['password'])
    return request


def prove(before_characters, characters, before_shared, shared, issuer, sequence,
          request, *, names, result):
    """The journal's final image must be the exact selected channel transition."""
    if not isinstance(request, dict) or set(request) != {'op', 'row'} or request['op'] != 'CHANNEL_ACTION':
        raise ValueError('LOCAL_CUSTODY_CHANNEL_ENTITLEMENT')
    expected = copy.deepcopy(before_shared)
    actual_result = apply(before_characters, expected, issuer, sequence, request['row'],
                          now=shared['clock'], names=names)
    if actual_result != result or before_characters != characters:
        raise ValueError('LOCAL_CUSTODY_CHANNEL_ENTITLEMENT')
    bookkeeping = {'revision', 'sequences', 'receipts', 'retired'}
    if any(expected.get(key) != shared.get(key) for key in (set(expected) | set(shared)) - bookkeeping):
        raise ValueError('LOCAL_CUSTODY_CHANNEL_ENTITLEMENT')


class ChannelStoreMixin:
    """Optional strict schema extension on the existing recoverable store."""
    @contextmanager
    def _channel_locked(self):
        # The live LocalCharacters client already lends its exclusive session
        # fd. Standalone stores lend a temporary fd for this one nested draft /
        # transact call too; opening a second independent flock would conflict.
        with self._mutex:
            if self.session_lock is not None:
                with self._locked():
                    yield
                return
            path = self._path('.session.lock')
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd = secure_open(path, os.O_RDWR | os.O_CREAT | NOFOLLOW | CLOEXEC, 0o600)
            try:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise ValueError('LOCAL_CUSTODY_SESSION_BUSY') from None
                self.session_lock = fd
                try:
                    with self._locked():
                        yield
                finally:
                    self.session_lock = None
            finally:
                os.close(fd)

    def _validate_shared_channels(self, characters, shared):
        validate(characters, shared)
        special = [m for inbox in shared.get('chat', {}).values() for m in inbox
                   if isinstance(m, dict) and m.get('kind') in ('CHANNEL', 'CHANNEL_NOTICE')]
        if not special:
            return self._validate_custody_locked(characters, shared)
        sanitized = copy.deepcopy(shared)
        ids = set()
        for recipient, inbox in shared.get('chat', {}).items():
            if recipient not in characters or not isinstance(inbox, list) or len(inbox) > _custody().MAX_CHAT_INBOX:
                raise ValueError('LOCAL_CUSTODY_CHAT_CAPACITY')
            for message in inbox:
                if message.get('id') in ids:
                    raise ValueError('LOCAL_CUSTODY_CHAT_INVALID')
                ids.add(message.get('id'))
                if message.get('kind') in ('CHANNEL', 'CHANNEL_NOTICE'):
                    validate_message(message, recipient, characters)
            sanitized['chat'][recipient] = [m for m in inbox if m.get('kind') not in ('CHANNEL', 'CHANNEL_NOTICE')]
        # Existing generic validation still verifies every original chat row,
        # character envelope, physical asset, coin and receipt unchanged.
        return self._validate_custody_locked(characters, sanitized)

    def channel_action(self, issuer, sequence, row, *, now=None):
        c = _custody(); c.identity(issuer); c.integer(sequence, 1, c.MAX_SEQUENCE)
        moment = c.clock(time.time() if now is None else now)
        with self._channel_locked():
            self._recover_locked()
            characters = {key: self._character(key) for key in self._roster()}
            shared = self._shared()
            self._validate(characters, shared)
            request = canonical_request(row, shared, issuer, sequence)
            names = {r['id']: r['name'] for r in self._read('characters.json', c.MAX_BYTES)['characters']}
            def transform(payloads, target):
                return apply(characters, target, issuer, sequence, request, now=moment, names=names)
            return self.transact(issuer, sequence, dict(op='CHANNEL_ACTION', row=request), [], transform)


def notice_event(notice, name, speaker, slot):
    return dict(event='CHAT_MSG_CHANNEL_NOTICE',
                args=[notice, speaker, 'GG', name, speaker, '', 0, slot, name, slot])


def message_event(message, speaker):
    if message['kind'] == 'CHANNEL_NOTICE':
        return notice_event(message['notice'], message['channel_name'], speaker, message['channel_slot'])
    return dict(event='CHAT_MSG_CHANNEL', args=[message['text'], speaker, 'GG',
                message['channel_name'], speaker, '', 0, message['channel_slot'],
                message['channel_name'], message['channel_slot']])


class SharedLocalChannelsMixin:
    """Small opt-in hooks; central adapter decides when to call these methods."""
    def _shared_channel_reserved_slots_locked(self):
        snapshot = self._shared_custody_locked()
        return reserved_slots(snapshot['shared'], self._local_character_id) if snapshot else set()

    def _shared_channel_selection_locked(self, row, snapshot):
        if snapshot is None:
            return None
        frozen = 'channel_id' in row or 'channel_revision' in row
        if row.get('shared_channel') is False:
            if frozen:
                raise ValueError('CHANNEL_CHANGED')
            return None
        name = row.get('name', row.get('target'))
        rooms = snapshot['shared'].get('shared_channels', {})
        character = self._local_character_id
        if isinstance(name, str) and name.isdecimal():
            slot = int(name)
            room = next((r for r in rooms.values() if r['slots'].get(character) == slot), None)
        else:
            room = next((r for r in rooms.values() if isinstance(name, str) and r['name'].casefold() == name.casefold()), None)
        if frozen and (not room or row.get('channel_id', channel_id(room['name'])) != channel_id(room['name'])):
            raise ValueError('CHANNEL_CHANGED')
        known_join = room and row.get('op') == 'ChannelJoin' and not any(
            r['name'].casefold() == room['name'].casefold() and 'player' in r['members']
            for r in self._services['channels'])
        if row.get('shared_channel') is True or frozen or known_join or room and character in room['members']:
            if not room:
                return dict(name=channel_name(name), channel_id=channel_id(name))
            return dict(name=room['name'], channel_id=channel_id(room['name']), channel_revision=room['revision'])
        offer = snapshot['shared'].get('channel_invites', {}).get(character)
        if room and offer and offer['expires'] > max(snapshot['shared']['clock'], time.time()) and offer['channel'] == channel_id(room['name']):
            return dict(name=room['name'], channel_id=channel_id(room['name']), channel_revision=room['revision'])
        return None

    def _shared_channel_command_locked(self, row, snapshot):
        op = row.get('op', '')
        if not op.startswith('Channel') or snapshot is None:
            return None
        rooms = snapshot['shared'].get('shared_channels', {})
        character = self._local_character_id
        prior = snapshot['shared']['receipts'].get(character + ':' + str(row.get('custody_sequence', '')))
        old_sequence = type(row.get('custody_sequence')) is int and 1 <= row['custody_sequence'] <= snapshot['shared']['sequences'].get(character, 0)
        if row.get('shared_channel') is False:
            if 'channel_id' in row or 'channel_revision' in row or prior and prior['request'].get('op') == 'CHANNEL_ACTION':
                raise ValueError('CHANNEL_CHANGED')
            if old_sequence:
                raise ValueError('LOCAL_CUSTODY_RECEIPT_EXPIRED')
            return None
        if prior and prior['request'].get('op') == 'CHANNEL_ACTION':
            previous = prior['request']['row']
            if (op != previous['op'] or
                    row.get('name') not in (previous['name'], str(prior['result']['slot'])) or
                    row.get('channel_id', previous['id']) != previous['id'] or
                    row.get('channel_revision', previous['revision']) != previous['revision']):
                raise ValueError('LOCAL_CUSTODY_REPLAY_CHANGED')
            selection = dict(name=previous['name'], channel_id=previous['id'], channel_revision=previous['revision'])
        elif old_sequence:
            raise ValueError('LOCAL_CUSTODY_RECEIPT_EXPIRED')
        else:
            if op == 'ChannelListAll' and reserved_slots(snapshot['shared'], character):
                names = [r['name'] for r in self._services['channels'] if 'player' in r['members']]
                names += [r['name'] for r in rooms.values() if character in r['members']]
                return [dict(event='CHAT_MSG_SYSTEM', args=[', '.join(names)])]
            selection = self._shared_channel_selection_locked(row, snapshot)
        if selection is None:
            return None
        if row.get('channel_id', selection['channel_id']) != selection['channel_id']:
            raise ValueError('CHANNEL_CHANGED')
        request = dict(op=op, **selection)
        for field in ('channel_id', 'channel_revision', 'password', 'text'):
            if field in row:
                request[field] = row[field]
        if op in TARGET_OPS:
            target = row.get('player', row.get('target'))
            if isinstance(target, str) and target.casefold() in ('target', 'mouseover', 'pet'):
                raise ValueError('CHANNEL_SAVED_CHARACTER_REQUIRED')
            request['target'] = self._shared_person_locked(target, snapshot)
            if request['target'] is None:
                raise ValueError('CHANNEL_SAVED_CHARACTER_REQUIRED')
        room = rooms.get(selection['channel_id'])
        names = {r['id']: r['name'] for r in snapshot['roster']}
        if op in ('ChannelList', 'ChannelDisplayOwner'):
            if not room or character not in room['members']:
                raise ValueError('CHANNEL_NOT_JOINED')
            text = ', '.join(names[k] for k in room['members']) if op == 'ChannelList' else names[room['owner']]
            slot = room['slots'][character]
            return [dict(event='CHAT_MSG_CHANNEL_LIST', args=[text, '', 'GG', room['name'], '', '', 0, slot, room['name'], slot])]
        if self._player_defeated_locked():
            raise ValueError('PLAYER_DEFEATED')
        if self._services['taxi_flight']:
            raise ValueError('TAXI_IN_PROGRESS')
        result = self._shared_execute_locked(row, lambda store, owner, seq, revision:
                                             store.channel_action(owner, seq, request))
        if result.get('replayed'):
            return []
        value = result['result']
        if op == 'ChannelMessage':
            return [message_event(dict(kind='CHANNEL', text=value['text'], channel_name=request['name'],
                                       channel_slot=value['slot']), names[character])]
        return [notice_event(value['notice'], request['name'], names[character], value['slot'])] if value['notice'] else []

    def _shared_channel_chat_locked(self, row, snapshot):
        if row.get('op') != 'Chat' or row.get('chat_type', 'SAY') != 'CHANNEL':
            return None
        if snapshot is None:
            return None
        character = self._local_character_id
        prior = snapshot['shared']['receipts'].get(character + ':' + str(row.get('custody_sequence', '')))
        if row.get('shared_channel') is False:
            if ('channel_id' in row or 'channel_revision' in row or
                    prior and prior['request'].get('op') == 'CHANNEL_ACTION'):
                raise ValueError('CHANNEL_CHANGED')
            if type(row.get('custody_sequence')) is int and 1 <= row['custody_sequence'] <= snapshot['shared']['sequences'].get(character, 0):
                raise ValueError('LOCAL_CUSTODY_RECEIPT_EXPIRED')
            return None
        if prior and prior['request'].get('op') == 'CHANNEL_ACTION':
            previous = prior['request']['row']
            if (previous['op'] != 'ChannelMessage' or row.get('target') not in (
                    previous['name'], str(prior['result']['slot'])) or
                    row.get('channel_id', previous['id']) != previous['id'] or
                    row.get('channel_revision', previous['revision']) != previous['revision']):
                raise ValueError('LOCAL_CUSTODY_REPLAY_CHANGED')
            selection = dict(name=previous['name'])
        elif type(row.get('custody_sequence')) is int and 1 <= row['custody_sequence'] <= snapshot['shared']['sequences'].get(character, 0):
            raise ValueError('LOCAL_CUSTODY_RECEIPT_EXPIRED')
        else:
            selection = self._shared_channel_selection_locked(row, snapshot)
        if selection is None:
            return None
        request = dict(row, op='ChannelMessage', name=selection['name'], shared_channel=True)
        return self._shared_channel_command_locked(request, snapshot)

    def _shared_channels_view_locked(self, value, snapshot):
        if snapshot is None:
            return value
        value = copy.deepcopy(value); character = self._local_character_id
        names = {r['id']: r['name'] for r in snapshot['roster']}
        channels = value['channels']; rooms = snapshot['shared'].get('shared_channels', {})
        channels['shared_available'] = True
        for row in channels['rows']:
            row['slot'] = next((i + 1 for i, name in enumerate(channels['slots']) if name == row['name']), 0)
        for key, room in rooms.items():
            if character not in room['members']:
                continue
            slot = room['slots'][character]
            if channels['slots'][slot - 1] is not None:
                raise ValueError('CHANNEL_JOIN_CAPACITY')
            channels['slots'][slot - 1] = room['name']
            row = {field: copy.deepcopy(room[field]) for field in ROOM_FIELDS - {'password', 'slots'}}
            row.update(shared_channel=True, channel_id=key, channel_revision=room['revision'],
                       builtin=False, owner_name=names[room['owner']],
                       member_names=[names[k] for k in room['members']], slot=slot,
                       player_id=character, can_manage=authority(room, character),
                       is_owner=room['owner'] == character)
            channels['rows'].append(row)
        channels['shared_invite'] = copy.deepcopy(snapshot['shared'].get('channel_invites', {}).get(character))
        if channels['shared_invite'] and channels['shared_invite']['expires'] <= max(snapshot['shared']['clock'], time.time()):
            channels['shared_invite'] = None
        if channels['shared_invite']:
            offer = channels['shared_invite']; room = rooms[offer['channel']]
            offer.update(name=room['name'], sender_name=names[offer['sender']], shared_channel=True,
                         channel_id=offer['channel'], channel_revision=room['revision'])
        return value
