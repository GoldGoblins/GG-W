"""Consent over a paid physical charter shared by saved local characters.

The existing charter stays in its owner's inventory.  Offers contain references,
not item copies.  The finite GG charter policy still requires three signatures;
saved recipients have sixty seconds to log in and explicitly sign.  The journal
proof below permits only the exact charter mutation described by its receipt.
"""
from __future__ import annotations

import copy
import time

from backend import game_engine_items as items
from backend.game_engine_adapter_petitions import SIGNATURES, REGISTRAR
from backend.game_engine_adapter_social import guild_record

OFFER_SECONDS = 60
MAX_OFFERS = 10
_UNSET = object()


def _custody():
    # LocalCustodyStore inherits the mixin; avoid an import cycle at definition.
    from backend import game_engine_local_custody
    return game_engine_local_custody


def saved_identity(value):
    return isinstance(value, str) and len(value) == 32 and all(c in '0123456789abcdef' for c in value)


def charter(payload, owner, asset):
    c = _custody()
    c.identity(owner)
    matches = [item for item in payload.get('item_instances', []) if c.asset_id(owner, item) == asset]
    if len(matches) != 1:
        raise ValueError('PETITION_ITEM_CHANGED_OR_MISSING')
    item = matches[0]
    record = item.get('petition')
    if (item.get('definition_id') != 'item.guild_charter' or item.get('quantity') != 1
            or item.get('owner_id') != 'player' or item.get('location') != 'INVENTORY'
            or not isinstance(record, dict) or set(record) != {'title', 'owner', 'max_signatures', 'signers'}
            or record['owner'] != 'player' or record['max_signatures'] != SIGNATURES):
        raise ValueError('PETITION_RECORD_INVALID')
    title(record['title'])
    signers = record['signers']
    if (not isinstance(signers, list) or len(signers) > SIGNATURES or len(set(signers)) != len(signers)
            or owner in signers):
        raise ValueError('PETITION_RECORD_INVALID')
    return item


def title(value):
    c = _custody()
    c.short_text(value, 48)
    if not value or value != value.strip() or '  ' in value:
        raise ValueError('GUILD_NAME_INVALID')
    return value


def terms(owner, item):
    c = _custody()
    return c.digest(dict(owner=owner, asset=c.asset_id(owner, item),
                         title=item['petition']['title'], required=item['petition']['max_signatures']))


def guilded(characters, shared, character):
    local = characters[character]['payload'].get('player', {}).get('client_controls', {}).get('services', {}).get('guild', {})
    return bool(local.get('members', {}).get('player') or
                any(character in g['members'] for g in shared['guilds'].values()))


def projections(characters):
    """Bounded cached UI metadata; called on actual profile refresh, never paint."""
    c = _custody()
    result = {}
    for owner, envelope in characters.items():
        for item in envelope['payload'].get('item_instances', []):
            if item.get('definition_id') != 'item.guild_charter' or item.get('owner_id') != 'player':
                continue
            asset = c.asset_id(owner, item)
            try:
                physical = charter(envelope['payload'], owner, asset)
            except ValueError:
                continue
            result[asset] = dict(owner=owner, asset=asset, item=physical['instance_id'],
                                 terms=terms(owner, physical), record=copy.deepcopy(physical['petition']))
    return result


def validate(characters, shared):
    c = _custody()
    offers = shared.get('petition_offers', {})
    if not isinstance(offers, dict) or len(offers) > MAX_OFFERS:
        raise ValueError('PETITION_OFFER_CAPACITY')
    ids = set()
    for recipient, offer in offers.items():
        if (recipient not in characters or not isinstance(offer, dict)
                or set(offer) != {'id', 'owner', 'asset', 'terms', 'expires'}
                or offer['owner'] not in characters or offer['owner'] == recipient):
            raise ValueError('PETITION_OFFER_INVALID')
        key = offer['id']
        if (not isinstance(key, str) or len(key) != 41 or not key.startswith('petition-')
                or any(ch not in '0123456789abcdef' for ch in key[9:]) or key in ids):
            raise ValueError('PETITION_OFFER_INVALID')
        ids.add(key); c.clock(offer['expires'])
        item = charter(characters[offer['owner']]['payload'], offer['owner'], offer['asset'])
        if offer['terms'] != terms(offer['owner'], item) or recipient in item['petition']['signers']:
            raise ValueError('PETITION_TERMS_CHANGED')
        if len(item['petition']['signers']) >= SIGNATURES:
            raise ValueError('PETITION_ALREADY_SIGNED_OR_FULL')
        if any(not saved_identity(s) for s in item['petition']['signers']):
            raise ValueError('PETITION_MIXED_SIGNATURES')
    for owner, envelope in characters.items():
        for item in envelope['payload'].get('item_instances', []):
            if item.get('definition_id') != 'item.guild_charter' or not isinstance(item.get('petition'), dict):
                continue
            signers = item['petition'].get('signers', [])
            if any(saved_identity(s) for s in signers):
                charter(envelope['payload'], owner, c.asset_id(owner, item))
                if any(not saved_identity(s) for s in signers):
                    raise ValueError('PETITION_MIXED_SIGNATURES')
                if any(s not in characters for s in signers):
                    raise ValueError('PETITION_SIGNER_UNAVAILABLE')


def delete_blockers(character, characters, shared):
    result = []
    if character in shared.get('petition_offers', {}) or any(
            o['owner'] == character for o in shared.get('petition_offers', {}).values()):
        result.append('PETITION_OFFER')
    if any(character in p['record']['signers'] or character == p['owner'] and
           any(saved_identity(s) for s in p['record']['signers']) for p in projections(characters).values()):
        result.append('PETITION_SIGNATURE')
    return result


def prune(shared):
    offers = shared.setdefault('petition_offers', {})
    for recipient in list(offers):
        if offers[recipient]['expires'] <= shared['clock']:
            del offers[recipient]


def _request(row):
    shapes = {
        'PetitionOffer': {'op', 'owner', 'asset', 'terms', 'target'},
        'PetitionSign': {'op', 'owner', 'asset', 'terms', 'offer'},
        'PetitionClose': {'op', 'owner', 'asset', 'terms', 'offer'},
        'PetitionRename': {'op', 'owner', 'asset', 'terms', 'name'},
        'PetitionTurnIn': {'op', 'owner', 'asset', 'terms'},
        'PetitionDestroy': {'op', 'owner', 'asset', 'terms'},
    }
    if not isinstance(row, dict) or row.get('op') not in shapes or set(row) != shapes[row['op']]:
        raise ValueError('PETITION_COMMAND_INVALID')
    c = _custody(); c.identity(row['owner'])
    for field, prefix, length in (('asset', 'custody-', 40), ('terms', '', 64)):
        value = row[field]
        if (not isinstance(value, str) or len(value) != length or not value.startswith(prefix)
                or any(ch not in '0123456789abcdef' for ch in value[len(prefix):])):
            raise ValueError('PETITION_REFERENCE_INVALID')
    return row['op']


def apply(characters, shared, issuer, sequence, row, *, now, names=None):
    """Pure exact transition used by production and its recovery proof."""
    c = _custody(); c.identity(issuer); c.integer(sequence, 1, c.MAX_SEQUENCE)
    op = _request(row); owner = row['owner']
    if issuer not in characters or owner not in characters:
        raise ValueError('PETITION_OWNER_UNAVAILABLE')
    item = charter(characters[owner]['payload'], owner, row['asset'])
    record = item['petition']
    if row['terms'] != terms(owner, item):
        raise ValueError('PETITION_TERMS_CHANGED')
    shared['clock'] = max(shared['clock'], c.clock(now)); prune(shared)
    offers = shared['petition_offers']
    if op in ('PetitionOffer', 'PetitionRename', 'PetitionTurnIn', 'PetitionDestroy') and issuer != owner:
        raise ValueError('PETITION_OWNER_REQUIRED')
    if op not in ('PetitionRename', 'PetitionDestroy', 'PetitionClose'):
        if any(not saved_identity(s) for s in record['signers']):
            raise ValueError('PETITION_MIXED_SIGNATURES')
        if guilded(characters, shared, issuer) or guilded(characters, shared, owner):
            raise ValueError('GUILD_ALREADY_MEMBER')
    if op == 'PetitionOffer':
        target = c.identity(row['target'])
        if target not in characters or target == issuer:
            raise ValueError('PETITION_OTHER_PERSON_REQUIRED')
        if target in record['signers'] or len(record['signers']) >= SIGNATURES:
            raise ValueError('PETITION_ALREADY_SIGNED_OR_FULL')
        if guilded(characters, shared, target):
            raise ValueError('GUILD_ALREADY_MEMBER')
        ignored = characters[target]['payload'].get('player', {}).get('client_controls', {}).get('local_client', {}).get('ignores', [])
        if names and any(isinstance(n, str) and n.casefold() == names[issuer].casefold() for n in ignored):
            raise ValueError('PETITION_TARGET_IGNORES_PLAYER')
        if target in offers:
            raise ValueError('PETITION_OFFER_PENDING')
        key = 'petition-' + c.digest(dict(owner=issuer, sequence=sequence, asset=row['asset'], target=target))[:32]
        offers[target] = dict(id=key, owner=owner, asset=row['asset'], terms=row['terms'],
                              expires=shared['clock'] + OFFER_SECONDS)
        return dict(offer=key, asset=row['asset'], target=target)
    if op in ('PetitionSign', 'PetitionClose'):
        offer = offers.get(issuer)
        if not offer or any(offer[field] != row[field] for field in ('owner', 'asset', 'terms')) or offer['id'] != row['offer']:
            raise ValueError('PETITION_OFFER_CHANGED_OR_EXPIRED')
        if op == 'PetitionSign':
            if issuer in record['signers'] or len(record['signers']) >= SIGNATURES:
                raise ValueError('PETITION_ALREADY_SIGNED_OR_FULL')
            record['signers'].append(issuer)
        del offers[issuer]
        if len(record['signers']) >= SIGNATURES:
            for target in list(offers):
                if offers[target]['asset'] == row['asset']:
                    del offers[target]
        return dict(asset=row['asset'], signed=op == 'PetitionSign')
    for target in list(offers):
        if offers[target]['asset'] == row['asset']:
            del offers[target]
    if op == 'PetitionRename':
        record.update(title=title(row['name']), signers=[])
        return dict(asset=row['asset'], title=record['title'])
    if op == 'PetitionTurnIn':
        if len(record['signers']) != SIGNATURES:
            raise ValueError('PETITION_NEEDS_SIGNATURES')
        if any(s not in characters or guilded(characters, shared, s) for s in record['signers']):
            raise ValueError('PETITION_SIGNER_UNAVAILABLE')
        local_guilds = [e['payload'].get('player', {}).get('client_controls', {}).get('services', {}).get('guild', {}) for e in characters.values()]
        if any(g.get('name', '').casefold() == record['title'].casefold() for g in list(shared['guilds'].values()) + local_guilds):
            raise ValueError('GUILD_NAME_TAKEN')
        key = owner + ':' + str(sequence)
        new_guild = guild_record(record['title'], leader=owner, members=record['signers'])
        new_guild['leader'] = owner; shared['guilds'][key] = new_guild
        for member in new_guild['members']:
            shared['guild_invites'].pop(member, None)
    characters[owner]['payload']['item_instances'].remove(item)
    characters[owner]['payload']['inventory'] = items.inventory_counts(characters[owner]['payload']['item_instances'])
    return dict(asset=row['asset'], guild=key if op == 'PetitionTurnIn' else '')


def prove(before_assets, after_assets, before_characters, characters, before_shared, shared,
          issuer, sequence, request, source, *, names=None, result=_UNSET):
    """Narrow finite entitlement; no global omission of mutable item metadata."""
    if (not isinstance(request, dict) or set(request) != {'op', 'row'}
            or request['op'] != 'PETITION_ACTION' or source != request['row'].get('asset')):
        raise ValueError('LOCAL_CUSTODY_PETITION_ENTITLEMENT')
    expected_characters = copy.deepcopy(before_characters)
    expected_shared = copy.deepcopy(before_shared)
    expected_result = apply(expected_characters, expected_shared, issuer, sequence, request['row'], now=shared['clock'], names=names)
    if result is not _UNSET and result != expected_result:
        raise ValueError('LOCAL_CUSTODY_PETITION_ENTITLEMENT')
    if any(expected_characters[k]['payload'] != characters[k]['payload'] for k in before_characters):
        raise ValueError('LOCAL_CUSTODY_PETITION_ENTITLEMENT')
    for field in set(expected_shared) | set(shared):
        if field in ('revision', 'sequences', 'receipts'):
            continue
        if expected_shared.get(field) != shared.get(field):
            raise ValueError('LOCAL_CUSTODY_PETITION_ENTITLEMENT')
    key = request['row']['asset']; op = request['row']['op']
    if key not in before_assets:
        raise ValueError('LOCAL_CUSTODY_PETITION_ENTITLEMENT')
    if op in ('PetitionTurnIn', 'PetitionDestroy'):
        if key in after_assets:
            raise ValueError('LOCAL_CUSTODY_PETITION_ENTITLEMENT')
        del before_assets[key]
    else:
        if key not in after_assets:
            raise ValueError('LOCAL_CUSTODY_PETITION_ENTITLEMENT')
        before_assets[key] = after_assets[key]


class PetitionStoreMixin:
    def petition_action(self, issuer, sequence, row, *, now=None, expected_revision=None):
        op = _request(row); c = _custody()
        request = copy.deepcopy(row); owner = request['owner']
        selected = [owner] if op in ('PetitionSign', 'PetitionRename', 'PetitionTurnIn', 'PetitionDestroy') else []
        if expected_revision is not None and issuer not in selected:
            selected.append(issuer)
        expected = {} if expected_revision is None else {issuer: expected_revision}
        moment = c.clock(time.time() if now is None else now)
        def transform(payloads, shared):
            characters = {key: self._character(key) for key in self._roster()}
            for key, payload in payloads.items():
                characters[key]['payload'] = payload
            names = {r['id']: r['name'] for r in self._read('characters.json', c.MAX_BYTES)['characters']}
            return apply(characters, shared, issuer, sequence, request, now=moment, names=names)
        return self.transact(issuer, sequence, dict(op='PETITION_ACTION', row=request), selected, transform,
                             expected_revisions=expected, _petition_source=request['asset'])


class SharedLocalPetitionsMixin:
    def _shared_petition_projections_locked(self, snapshot):
        character = self._local_character_id
        result = {k:p for k,p in snapshot.get('petitions', {}).items() if p['owner'] != character}
        # Existing physical purchases/renames also update the active character.
        # Refresh its small actual charter set from memory, without profile IO.
        for physical in self._owned_charters_locked():
            asset = _custody().asset_id(character, physical)
            result[asset] = dict(owner=character, asset=asset, item=physical['instance_id'],
                                terms=terms(character, physical), record=copy.deepcopy(physical['petition']))
        return result

    def _shared_petition_reference_locked(self, row, projection, offer=None):
        expected = dict(petition_owner=projection['owner'], petition_asset=projection['asset'],
                        petition_terms=projection['terms'])
        if offer is not None:
            expected['petition_offer'] = offer['id']
        if any(row.get(k) != v for k, v in expected.items()):
            raise ValueError('PETITION_SHOWN_REFERENCE_CHANGED')
        return dict(owner=projection['owner'], asset=projection['asset'], terms=projection['terms'])

    def _shared_petition_command_locked(self, row, snapshot):
        op = row.get('op', ''); character = self._local_character_id; shared = snapshot['shared']
        cached = self._shared_petition_projections_locked(snapshot); offer = shared.get('petition_offers', {}).get(character)
        active = self._service_windows.get('petition')
        focused = next((p for p in cached.values() if p['owner'] == character and p['item'] == active), None)
        prior = shared['receipts'].get(character + ':' + str(row.get('custody_sequence', '')))
        replay = prior and prior['request'].get('op') == 'PETITION_ACTION'
        explicit_old = (type(row.get('custody_sequence')) is int and
                        1 <= row['custody_sequence'] <= shared['sequences'].get(character, 0))
        if explicit_old and op.startswith('Petition') and op not in ('PetitionOffer', 'PetitionSign', 'PetitionClose', 'PetitionRename', 'PetitionTurnIn'):
            raise ValueError('LOCAL_CUSTODY_RECEIPT_EXPIRED')
        in_shared_guild = any(character in g['members'] for g in shared['guilds'].values())
        if in_shared_guild and op in ('PetitionBuy', 'PetitionRequestOffer', 'PetitionSign', 'PetitionOffer', 'PetitionTurnIn') and not replay:
            raise ValueError('GUILD_ALREADY_MEMBER')
        own_items = [p for p in cached.values() if p['owner'] == character]
        shared_owned = lambda p: any(saved_identity(s) for s in p['record']['signers']) or any(
            o['asset'] == p['asset'] for o in shared.get('petition_offers', {}).values())
        projection = None; request = None
        if op == 'PetitionOffer':
            raw_target = row.get('target')
            target = None if isinstance(raw_target,str) and raw_target.casefold() in ('target','mouseover','pet') else self._shared_person_locked(raw_target, snapshot)
            if target is None:
                if explicit_old:
                    raise ValueError('LOCAL_CUSTODY_REPLAY_CHANGED' if replay else 'LOCAL_CUSTODY_RECEIPT_EXPIRED')
                if focused and shared_owned(focused):
                    raise ValueError('PETITION_MIXED_SIGNATURES')
                return None
            self._service_session_locked(row, 'petition')
            if focused is None:
                raise ValueError('PETITION_ITEM_CHANGED_OR_MISSING')
            if self._services.get('petition_offer'):
                raise ValueError('PETITION_OFFER_PENDING')
            projection = focused
            request = dict(op=op, target=target, **self._shared_petition_reference_locked(row, projection))
        elif op in ('PetitionSign', 'PetitionClose') and (offer and not active or replay or explicit_old or row.get('petition_offer') is not None):
            if row.get('session') != self._service_generation:
                raise ValueError('SERVICE_WINDOW_CHANGED_OR_CLOSED')
            if offer:
                projection = cached.get(offer['asset'])
                if projection is None:
                    raise ValueError('PETITION_ITEM_CHANGED_OR_MISSING')
                request = dict(op=op, offer=offer['id'], **self._shared_petition_reference_locked(row, projection, offer))
            elif replay:
                request = copy.deepcopy(prior['request']['row'])
                fields = dict(petition_owner=request['owner'], petition_asset=request['asset'],
                              petition_terms=request['terms'], petition_offer=request['offer'])
                if request['op'] != op or any(row.get(k) != v for k, v in fields.items()):
                    raise ValueError('LOCAL_CUSTODY_REPLAY_CHANGED')
            else:
                raise ValueError('LOCAL_CUSTODY_RECEIPT_EXPIRED')
        elif op == 'PetitionRename' and (focused and shared_owned(focused) or replay or explicit_old):
            self._service_session_locked(row, 'petition')
            projection = focused
            if replay:
                request = copy.deepcopy(prior['request']['row'])
                if request['op'] != op or row.get('name') != request['name']:
                    raise ValueError('LOCAL_CUSTODY_REPLAY_CHANGED')
                expected = dict(petition_owner=request['owner'], petition_asset=request['asset'], petition_terms=request['terms'])
                if any(row.get(k) != v for k, v in expected.items()):
                    raise ValueError('LOCAL_CUSTODY_REPLAY_CHANGED')
            elif projection:
                request = dict(op=op, name=row.get('name'), **self._shared_petition_reference_locked(row, projection))
            else:
                raise ValueError('LOCAL_CUSTODY_RECEIPT_EXPIRED')
        elif op == 'PetitionTurnIn' and (any(shared_owned(p) for p in own_items) or replay or explicit_old):
            self._service_session_locked(row, 'registrar'); self._service_person_locked(REGISTRAR, nearby=True)
            projection = next((p for p in own_items if p['asset'] == row.get('petition_asset')), None)
            if replay:
                request = copy.deepcopy(prior['request']['row'])
                expected = dict(petition_owner=request['owner'], petition_asset=request['asset'], petition_terms=request['terms'])
                if request['op'] != op or any(row.get(k) != v for k, v in expected.items()):
                    raise ValueError('LOCAL_CUSTODY_REPLAY_CHANGED')
            elif projection:
                request = dict(op=op, **self._shared_petition_reference_locked(row, projection))
            else:
                raise ValueError('PETITION_SHOWN_REFERENCE_CHANGED')
        elif op == 'InventoryDestroy':
            projection = next((p for p in own_items if p['item'] == row.get('item') and shared_owned(p)), None)
            if projection:
                request = dict(op='PetitionDestroy', owner=character, asset=projection['asset'], terms=projection['terms'])
            elif replay and prior['request']['row'].get('op') == 'PetitionDestroy':
                request = copy.deepcopy(prior['request']['row'])
                if _custody().asset_id(character, dict(instance_id=row.get('item'))) != request['asset']:
                    raise ValueError('LOCAL_CUSTODY_REPLAY_CHANGED')
            elif explicit_old:
                raise ValueError('LOCAL_CUSTODY_RECEIPT_EXPIRED')
        elif op in ('PetitionBuy', 'PetitionRequestOffer') and any(character in g['members'] for g in shared['guilds'].values()):
            raise ValueError('GUILD_ALREADY_MEMBER')
        if request is None:
            return None
        if op != 'PetitionClose':
            if self._player_defeated_locked():
                raise ValueError('PLAYER_DEFEATED')
            if self._services['taxi_flight']:
                raise ValueError('TAXI_IN_PROGRESS')
        result = self._shared_execute_locked(row, lambda store, owner, seq, revision:
            store.petition_action(owner, seq, request, expected_revision=revision))
        if result.get('replayed'):
            return []
        if op in ('PetitionRename', 'PetitionTurnIn', 'InventoryDestroy'):
            self._services['petition_offer'] = None
        if op in ('PetitionTurnIn', 'InventoryDestroy'):
            self._service_windows['petition'] = None
        event_names = ['PETITION_UPDATE']
        if op in ('PetitionSign', 'PetitionClose', 'PetitionTurnIn', 'InventoryDestroy'):
            event_names = ['PETITION_CLOSED']
        if op in ('PetitionTurnIn', 'InventoryDestroy'):
            event_names.append('BAG_UPDATE')
        emitted = [{'event': name, 'args': [0] if name == 'BAG_UPDATE' else []} for name in event_names]
        if op == 'PetitionTurnIn':
            emitted += [{'event': 'PLAYER_GUILD_UPDATE', 'args': ['player']}, {'event': 'GUILD_ROSTER_UPDATE', 'args': []}]
        return emitted

    def _petition_view_locked(self):
        snapshot = self._shared_custody_locked()
        if snapshot is None:
            return super()._petition_view_locked()
        character = self._local_character_id; cached = self._shared_petition_projections_locked(snapshot)
        offers = snapshot['shared'].get('petition_offers', {})
        offer = offers.get(character)
        now = max(snapshot['shared']['clock'], time.time())
        active = self._service_windows.get('petition')
        focused = next((p for p in cached.values() if p['owner'] == character and p['item'] == active), None)
        remote = cached.get(offer['asset']) if offer and offer['expires'] > now and not active else None
        names = {r['id']: r['name'] for r in snapshot['roster']}
        selected = remote or focused
        if selected and (remote or any(saved_identity(s) for s in selected['record']['signers'])):
            record = selected['record']
            value = dict(open=True, registrar_open=self._service_windows['registrar'], cost=10000,
                record=dict(item=selected['asset'] if remote else selected['item'], title=record['title'],
                    owner=selected['owner'], signers=list(record['signers']),
                    max_signatures=record['max_signatures'], owner_name=names[selected['owner']],
                    is_originator=selected['owner'] == character, signer_names=[names.get(s, s) for s in record['signers']]),
                can_sign=bool(remote and character not in record['signers'] and len(record['signers']) < SIGNATURES and
                    not self._services['guild'] and not any(character in g['members'] for g in snapshot['shared']['guilds'].values())),
                owned=[], offer=None)
        else:
            value = super()._petition_view_locked()
        if any(character in g['members'] for g in snapshot['shared']['guilds'].values()):
            value['can_sign'] = False
        for row in value['owned']:
            projection = next((p for p in cached.values() if p['owner'] == character and p['item'] == row['item']), None)
            if projection:
                row.update(petition_owner=character, petition_asset=projection['asset'], petition_terms=projection['terms'])
        if selected:
            value['record'].update(petition_owner=selected['owner'], petition_asset=selected['asset'], petition_terms=selected['terms'])
            if remote:
                value['record']['petition_offer'] = offer['id']
        # The saved-character picker uses exact identities and displayed refs.
        value['saved_recipients'] = [dict(id=r['id'], name=r['name'], level=r.get('level', 1)) for r in snapshot['roster'] if r['id'] != character]
        if selected and not remote and not value['owned']:
            value['owned'] = [dict(item=p['item'], title=p['record']['title'], petition_owner=character,
                                   petition_asset=p['asset'], petition_terms=p['terms']) for p in cached.values() if p['owner'] == character]
        return value
