"""Explicit two-character consent over real saved items and copper.

This account-local handoff deliberately has no offline actor or NPC wallet.
Offers only pin references; the second explicit acceptance moves whole physical
stacks through LocalCustodyStore's existing recoverable two-file transaction.
The separate seventh slot pins gear for a consented enchantment service without
transferring its ownership. Partial item-stack transfers remain unsupported.
"""
from __future__ import annotations

import copy
import time

from backend import game_engine_items as items, game_engine_trade as trade
from backend import game_engine_local_direct_trade_enchant as enchant
from backend import game_engine_enchants as enchants

MAX_TRADES = 5
MAX_SLOTS = 6
MAX_COPPER = 2_000_000_000
OFFER_SECONDS = 600
REFERENCE_FIELDS = {'asset', 'instance', 'quantity', 'slot', 'item_hash', 'definition_hash'}
TRADE_FIELDS = {'id', 'owner', 'recipient', 'revision', 'expires', 'joined', 'sides', 'accepts', 'terms'}
CONTEXT = {'id', 'owner', 'recipient', 'revision', 'terms'}


def _custody():
    # This mixin is imported by LocalCustodyStore; defer the circular dependency.
    from backend import game_engine_local_custody
    return game_engine_local_custody


def _item_hash(item):
    c = _custody()
    return c.digest({k: v for k, v in item.items() if k not in c.CONTEXT_FIELDS})


def _material(item, catalog=None):
    """Keep binding, container and wrapped-content rules through the handoff."""
    c = _custody()
    if not isinstance(item, dict) or item.get('bound_to'):
        raise ValueError('DIRECT_TRADE_ITEM_BOUND')
    c.integer(item.get('quantity'), 1, 999)
    if item.get('kind') in ('QUEST', 'CONTAINER') or item.get('contents'):
        raise ValueError('DIRECT_TRADE_ITEM_INELIGIBLE')
    policies = []
    definition = None
    if catalog is not None:
        definition = items.definition(catalog, item.get('definition_id'))
        ok, result = trade.tradeable_definition(definition)
        if not ok:
            raise ValueError(result['error'])
        tags = definition.get('tags', [])
        if not isinstance(tags, (list, tuple)) or any(not isinstance(tag, str) for tag in tags):
            raise ValueError('DIRECT_TRADE_DEFINITION_INVALID')
        # Scan all authored tags, rather than quietly truncating binding flags.
        if {tag.upper() for tag in tags} & trade.BLOCKED_TAGS:
            raise ValueError('DIRECT_TRADE_ITEM_BOUND')
        bonding = definition.get('bonding', 0)
        c.integer(bonding, 0, 5)
        if bonding in (1, 4, 5):
            raise ValueError('DIRECT_TRADE_ITEM_BOUND')
        limit = c.integer(definition.get('stack_limit', 1), 1, 999)
        if item['quantity'] > limit:
            raise ValueError('DIRECT_TRADE_STACK_INVALID')
        policies.append(dict(id=definition['id'], kind=definition.get('kind', 'ITEM'),
                             tags=sorted(tags), bonding=bonding, stack_limit=limit))
    if item.get('definition_id') == 'item.gg_wrapped_gift':
        gift = item.get('gift')
        original = gift.get('original') if isinstance(gift, dict) else None
        if (item.get('gift_invalid') or item.get('gift_quarantine') or item['quantity'] != 1
                or not items.saved_gift_payload_valid(item) or not isinstance(original, dict)
                or original.get('definition_id') in ('item.gg_wrapped_gift', 'item.gg_wrapping_paper')
                or 'gift' in original or 'gift_quarantine' in original or original.get('quantity') != 1):
            raise ValueError('DIRECT_TRADE_WRAPPED_GIFT_INVALID')
        policies += _material(original, catalog)
        if catalog is not None:
            inside = items.definition(catalog, original['definition_id'])
            if inside.get('stack_limit', 1) != 1 or 'GIFT_WRAPPER' in inside.get('tags', []):
                raise ValueError('DIRECT_TRADE_WRAPPED_GIFT_INVALID')
    return policies


def reference(payload, owner, instance, catalog):
    """Freeze a shown physical backpack row, including complete item metadata."""
    c = _custody(); c.identity(owner)
    matches = [i for i in payload.get('item_instances', []) if i.get('instance_id') == instance]
    if len(matches) != 1:
        raise ValueError('DIRECT_TRADE_ITEM_CHANGED')
    item = matches[0]
    if item.get('owner_id') != 'player' or item.get('location') != 'INVENTORY':
        raise ValueError('DIRECT_TRADE_OWNED_BACKPACK_REQUIRED')
    slot = c.integer(item.get('slot_index'), 0, items.MAX_INVENTORY_SLOTS - 1)
    policies = _material(item, catalog)
    return dict(asset=c.asset_id(owner, item), instance=instance, quantity=item['quantity'], slot=slot,
                item_hash=_item_hash(item), definition_hash=c.digest(policies))


def _reference_item(payload, owner, ref, catalog=None):
    c = _custody()
    if not isinstance(ref, dict) or set(ref) != REFERENCE_FIELDS:
        raise ValueError('DIRECT_TRADE_REFERENCE_INVALID')
    asset = ref['asset']
    if (not isinstance(asset, str) or len(asset) != 40 or not asset.startswith('custody-')
            or any(ch not in '0123456789abcdef' for ch in asset[8:])):
        raise ValueError('DIRECT_TRADE_REFERENCE_INVALID')
    if not c.short_text(ref['instance'], 64):
        raise ValueError('DIRECT_TRADE_REFERENCE_INVALID')
    c.integer(ref['quantity'], 1, 999); c.integer(ref['slot'], 0, items.MAX_INVENTORY_SLOTS - 1)
    c.LocalCustodyStore._hash(ref['item_hash']); c.LocalCustodyStore._hash(ref['definition_hash'])
    matches = [i for i in payload.get('item_instances', []) if i.get('instance_id') == ref['instance']]
    if len(matches) != 1:
        raise ValueError('DIRECT_TRADE_ITEM_CHANGED')
    item = matches[0]
    if (item.get('owner_id') != 'player' or item.get('location') != 'INVENTORY'
            or item.get('quantity') != ref['quantity'] or item.get('slot_index') != ref['slot']
            or c.asset_id(owner, item) != asset or _item_hash(item) != ref['item_hash']):
        raise ValueError('DIRECT_TRADE_ITEM_CHANGED')
    policies = _material(item, catalog)
    if catalog is not None and c.digest(policies) != ref['definition_hash']:
        raise ValueError('DIRECT_TRADE_DEFINITION_CHANGED')
    return item


def terms(offer):
    return _custody().digest({k: offer[k] for k in ('id', 'owner', 'recipient', 'revision', 'joined', 'sides')})


def context(offer):
    """Immutable command bindings; these survive completion for exact replay."""
    return {key: copy.deepcopy(offer[key]) for key in CONTEXT}


def find(shared, character):
    return next((offer for offer in shared.get('direct_trades', {}).values()
                 if character in (offer['owner'], offer['recipient'])), None)


def validate(characters, shared, catalog=None, *, gear_tables=None):
    c = _custody(); offers = shared.get('direct_trades', {})
    if not isinstance(offers, dict) or len(offers) > MAX_TRADES:
        raise ValueError('DIRECT_TRADE_CAPACITY')
    participants = set()
    for key, offer in offers.items():
        if not isinstance(offer, dict) or set(offer) != TRADE_FIELDS:
            raise ValueError('DIRECT_TRADE_RECORD_INVALID')
        _id(key)
        pair = (offer['owner'], offer['recipient'])
        if key != offer['id'] or pair[0] == pair[1] or any(p not in characters or p in participants for p in pair):
            raise ValueError('DIRECT_TRADE_PARTICIPANT_INVALID')
        for p in pair:
            c.identity(p)
        participants.update(pair); c.integer(offer['revision'], 1, c.MAX_SEQUENCE); c.clock(offer['expires'])
        if (type(offer['joined']) is not bool or not isinstance(offer['sides'], dict)
                or not isinstance(offer['accepts'], dict) or set(offer['sides']) != set(pair)
                or set(offer['accepts']) != set(pair)):
            raise ValueError('DIRECT_TRADE_RECORD_INVALID')
        for p in pair:
            side = offer['sides'][p]
            if not isinstance(side, dict) or set(side) not in (enchant.LEGACY_SIDE_FIELDS, enchant.SIDE_FIELDS):
                raise ValueError('DIRECT_TRADE_RECORD_INVALID')
            slots = side['slots']
            if not isinstance(slots, dict) or len(slots) > MAX_SLOTS or set(slots) - {str(i) for i in range(1, 7)}:
                raise ValueError('DIRECT_TRADE_SLOT_INVALID')
            assets = set()
            for ref in slots.values():
                _reference_item(characters[p]['payload'], p, ref, catalog)
                if ref['asset'] in assets:
                    raise ValueError('DIRECT_TRADE_ITEM_ALREADY_OFFERED')
                assets.add(ref['asset'])
            money = c.integer(side['copper'], 0, MAX_COPPER)
            if money > c.LocalCustodyStore._money(characters[p]['payload']):
                raise ValueError('DIRECT_TRADE_MONEY_CHANGED')
        enchant.validate(characters, offer, catalog, gear_tables=gear_tables)
        recipient_side = offer['sides'][pair[1]]
        if not offer['joined'] and (recipient_side['slots'] or recipient_side['copper']
                or recipient_side.get('enchant_target') or recipient_side.get('enchant_service')
                or any(offer['accepts'].values())):
            raise ValueError('DIRECT_TRADE_RECIPIENT_CONSENT_REQUIRED')
        if (offer['terms'] != terms(offer) or any(not isinstance(value, str) or value not in ('', offer['terms'])
                                               for value in offer['accepts'].values())):
            raise ValueError('DIRECT_TRADE_TERMS_CHANGED')
        if all(offer['accepts'].values()):
            raise ValueError('DIRECT_TRADE_COMPLETED_NOT_SETTLED')


def delete_blockers(character, characters, shared):
    return ['DIRECT_TRADE'] if find(shared, character) else []


def prune(shared):
    for key, offer in list(shared.get('direct_trades', {}).items()):
        if offer['expires'] <= shared['clock']:
            del shared['direct_trades'][key]


def projections(characters, shared):
    """Finite offered rows and service review, never an offline world replica."""
    result = {}
    for key, offer in shared.get('direct_trades', {}).items():
        result[key] = {p: {slot: copy.deepcopy(_reference_item(characters[p]['payload'], p, ref))
                          for slot, ref in side['slots'].items()} for p, side in offer['sides'].items()}
        for p, side in offer['sides'].items():
            if side.get('enchant_target'):
                result[key][p]['7'] = copy.deepcopy(enchant.target_item(characters[p]['payload'], p, side['enchant_target']))
            if side.get('enchant_service'):
                result[key][p]['enchant_service'] = enchant.service_view(characters, offer, p)
    return result


def _id(value):
    if (not isinstance(value, str) or len(value) != 38 or not value.startswith('trade-')
            or any(ch not in '0123456789abcdef' for ch in value[6:])):
        raise ValueError('DIRECT_TRADE_REFERENCE_INVALID')


def _request(row):
    c = _custody()
    if not isinstance(row, dict):
        raise ValueError('DIRECT_TRADE_COMMAND_INVALID')
    op = row.get('op')
    shape = {'op', 'target'} if op == 'TradeOpen' else {'op'} | CONTEXT
    if op == 'TradeSet':
        shape |= {'slot', 'item'}
    elif op == 'TradeClear':
        shape |= {'slot'}
    elif op == 'TradeMoney':
        shape |= {'money'}
    elif op == 'TradeEnchant':
        shape |= {'scroll', 'enchant_id', 'replace', 'bind'}
    if op not in ('TradeOpen', 'TradeJoin', 'TradeSet', 'TradeClear', 'TradeMoney', 'TradeAccept',
                  'TradeUnaccept', 'TradeCancel', 'TradeEnchant', 'TradeEnchantClear') or set(row) != shape:
        raise ValueError('DIRECT_TRADE_COMMAND_INVALID')
    if op == 'TradeOpen':
        c.identity(row['target'])
    else:
        _id(row['id']); c.identity(row['owner']); c.identity(row['recipient'])
        c.integer(row['revision'], 1, c.MAX_SEQUENCE); c.LocalCustodyStore._hash(row['terms'])
        if row['owner'] == row['recipient']:
            raise ValueError('DIRECT_TRADE_PARTICIPANT_INVALID')
    if op in ('TradeSet', 'TradeClear'):
        c.integer(row['slot'], 1, MAX_SLOTS + 1)
    if op == 'TradeMoney':
        c.integer(row['money'], 0, MAX_COPPER)
    if op == 'TradeEnchant':
        if (not isinstance(row['enchant_id'], str) or not row['enchant_id'] or len(row['enchant_id']) > 96
                or type(row['replace']) is not bool or type(row['bind']) is not bool):
            raise ValueError('DIRECT_TRADE_ENCHANT_SERVICE_INVALID')
    return op


def _changed(offer):
    c = _custody()
    offer['revision'] = c.integer(offer['revision'], 1, c.MAX_SEQUENCE - 1) + 1
    offer['terms'] = terms(offer)
    offer['accepts'] = {p: '' for p in offer['sides']}


def _complete(characters, offer, catalog):
    c = _custody(); pair = (offer['owner'], offer['recipient']); moved = {}
    outgoing = {p: [_reference_item(characters[p]['payload'], p, ref, catalog)
                    for _, ref in sorted(offer['sides'][p]['slots'].items())] for p in pair}
    for p in pair:
        payload = characters[p]['payload']
        other = pair[1] if p == pair[0] else pair[0]
        inventory = [i for i in payload['item_instances'] if i.get('owner_id') == 'player' and i.get('location') == 'INVENTORY']
        if len(payload['item_instances']) - len(outgoing[p]) + len(outgoing[other]) > items.MAX_WORLD_INSTANCES:
            raise ValueError('DIRECT_TRADE_WORLD_FULL')
        if len(inventory) - len(outgoing[p]) + len(outgoing[other]) > items.MAX_INVENTORY_SLOTS:
            raise ValueError('DIRECT_TRADE_INVENTORY_FULL')
        # Both sides must own the offered copper independently, even if their
        # incoming amount could have financed an otherwise unfunded offer.
        if c.LocalCustodyStore._money(payload) < offer['sides'][p]['copper']:
            raise ValueError('DIRECT_TRADE_MONEY_CHANGED')
    for p in pair:
        payload = characters[p]['payload']
        for item in outgoing[p]:
            payload['item_instances'].remove(item)
            item['custody_origin'] = c.origin(p, item)
        c.LocalCustodyStore._money(payload, -offer['sides'][p]['copper'])
    for p in pair:
        payload = characters[p]['payload']; other = pair[1] if p == pair[0] else pair[0]
        inventory = [i for i in payload['item_instances'] if i.get('owner_id') == 'player' and i.get('location') == 'INVENTORY']
        used = {i.get('slot_index') for i in inventory}
        free = sorted(set(range(items.MAX_INVENTORY_SLOTS)) - used)
        if len(free) < len(outgoing[other]):
            raise ValueError('DIRECT_TRADE_INVENTORY_FULL')
        ids = {i['instance_id'] for i in payload['item_instances']}; moved[p] = []
        for slot, item in zip(free, outgoing[other]):
            if item['instance_id'] in ids:
                item['instance_id'] = c.asset_id(other, item)
            if item['instance_id'] in ids:
                raise ValueError('DIRECT_TRADE_ITEM_ID_COLLISION')
            ids.add(item['instance_id'])
            item.update(owner_id='player', location='INVENTORY', slot_index=slot, container_id='', equipped_slot='')
            payload['item_instances'].append(item); moved[p].append(item['instance_id'])
        c.LocalCustodyStore._money(payload, offer['sides'][other]['copper'])
        c.LocalCustodyStore._sync_inventory(payload)
    return moved


def apply(characters, shared, issuer, sequence, row, *, now, catalog=None, names=None, gear_tables=None):
    """Finite deterministic transition, also replayed by the recovery proof."""
    c = _custody(); c.identity(issuer); c.integer(sequence, 1, c.MAX_SEQUENCE)
    op = _request(row)
    if issuer not in characters:
        raise ValueError('DIRECT_TRADE_CHARACTER_UNAVAILABLE')
    shared['clock'] = max(shared['clock'], c.clock(now)); prune(shared)
    offers = shared.setdefault('direct_trades', {})
    if op == 'TradeOpen':
        target = row['target']
        if target not in characters or target == issuer:
            raise ValueError('DIRECT_TRADE_OTHER_CHARACTER_REQUIRED')
        if len(offers) >= MAX_TRADES or find(shared, issuer) or find(shared, target):
            raise ValueError('DIRECT_TRADE_ALREADY_PENDING')
        ignored = characters[target]['payload'].get('player', {}).get('client_controls', {}).get('local_client', {}).get('ignores', [])
        if names and any(isinstance(n, str) and n.casefold() == names[issuer].casefold() for n in ignored):
            raise ValueError('DIRECT_TRADE_TARGET_IGNORES_PLAYER')
        key = 'trade-' + c.digest(dict(owner=issuer, recipient=target, sequence=sequence))[:32]
        offer = dict(id=key, owner=issuer, recipient=target, revision=1, joined=False,
                     expires=c.clock(shared['clock'] + OFFER_SECONDS),
                     sides={p: dict(slots={}, copper=0) for p in (issuer, target)},
                     accepts={p: '' for p in (issuer, target)})
        offer['terms'] = terms(offer); offers[key] = offer
        return dict(trade=key, completed=False, revision=1)
    offer = offers.get(row['id'])
    if not offer or issuer not in offer['sides'] or any(row[k] != offer[k] for k in CONTEXT):
        raise ValueError('DIRECT_TRADE_OFFER_CHANGED_OR_EXPIRED')
    if op == 'TradeCancel':
        del offers[offer['id']]
        return dict(trade=offer['id'], completed=False, cancelled=True)
    if op == 'TradeJoin':
        if issuer != offer['recipient'] or offer['joined']:
            raise ValueError('DIRECT_TRADE_RECIPIENT_CONSENT_REQUIRED')
        offer['joined'] = True; _changed(offer)
    elif issuer == offer['recipient'] and not offer['joined']:
        raise ValueError('DIRECT_TRADE_RECIPIENT_CONSENT_REQUIRED')
    elif op == 'TradeSet':
        ref = row['item']; side = offer['sides'][issuer]
        if row['slot'] == 7:
            enchant.set_target(characters, offer, issuer, ref, catalog, gear_tables=gear_tables)
        else:
            _reference_item(characters[issuer]['payload'], issuer, ref, catalog)
            pinned = [side.get('enchant_target'), (side.get('enchant_service') or {}).get('scroll')]
            if (any(ref['asset'] == value['asset'] for slot, value in side['slots'].items() if slot != str(row['slot']))
                    or any(value and ref['asset'] == value['asset'] for value in pinned)):
                raise ValueError('DIRECT_TRADE_ITEM_ALREADY_OFFERED')
            side['slots'][str(row['slot'])] = copy.deepcopy(ref)
        _changed(offer)
    elif op == 'TradeClear':
        if row['slot'] == 7:enchant.clear_target(offer, issuer)
        else:offer['sides'][issuer]['slots'].pop(str(row['slot']), None)
        _changed(offer)
    elif op == 'TradeEnchant':
        service = enchant.service_reference(characters, offer, issuer, row['scroll'], row['enchant_id'], catalog,
                                            replace=row['replace'], bind=row['bind'], gear_tables=gear_tables)
        enchant.set_service(characters, offer, issuer, service, catalog, gear_tables=gear_tables); _changed(offer)
    elif op == 'TradeEnchantClear':
        enchant.extended(offer['sides'][issuer])['enchant_service'] = None; _changed(offer)
    elif op == 'TradeMoney':
        if row['money'] > c.LocalCustodyStore._money(characters[issuer]['payload']):
            raise ValueError('DIRECT_TRADE_MONEY_CHANGED')
        offer['sides'][issuer]['copper'] = row['money']; _changed(offer)
    elif op == 'TradeUnaccept':
        offer['accepts'][issuer] = ''
    elif op == 'TradeAccept':
        if not offer['joined']:
            raise ValueError('DIRECT_TRADE_RECIPIENT_CONSENT_REQUIRED')
        if not any(side['slots'] or side['copper'] or side.get('enchant_service') for side in offer['sides'].values()):
            raise ValueError('DIRECT_TRADE_EMPTY_OFFER')
        # Recheck the complete offer, including the other saved character,
        # rather than treating an older acceptance as ownership authority.
        validate(characters, shared, catalog, gear_tables=gear_tables)
        offer['accepts'][issuer] = offer['terms']
        if all(offer['accepts'].values()):
            enchanted = enchant.complete(characters, offer, catalog, gear_tables=gear_tables)
            moved = _complete(characters, offer, catalog)
            del offers[offer['id']]
            result = dict(trade=offer['id'], completed=True, received=moved)
            if enchanted:result['enchanted'] = enchanted
            return result
    return dict(trade=offer['id'], completed=False, revision=offer['revision'])


def prove(before_characters, characters, before_shared, shared, issuer, sequence, request, *, names=None,
          result=None, before_assets=None, after_assets=None):
    """Recovery may only publish the exact consented transition in the receipt."""
    if not isinstance(request, dict) or set(request) != {'op', 'row'} or request['op'] != 'DIRECT_TRADE_ACTION':
        raise ValueError('LOCAL_CUSTODY_DIRECT_TRADE_ENTITLEMENT')
    expected_characters = copy.deepcopy(before_characters); expected_shared = copy.deepcopy(before_shared)
    expected_result = apply(expected_characters, expected_shared, issuer, sequence, request['row'], now=shared['clock'], names=names)
    if result is not None and expected_result != result:
        raise ValueError('LOCAL_CUSTODY_DIRECT_TRADE_ENTITLEMENT')
    if any(expected_characters[k]['payload'] != characters[k]['payload'] for k in before_characters):
        raise ValueError('LOCAL_CUSTODY_DIRECT_TRADE_ENTITLEMENT')
    bookkeeping = {'revision', 'sequences', 'receipts', 'retired'}
    for key in set(expected_shared) | set(shared):
        if key not in bookkeeping and expected_shared.get(key) != shared.get(key):
            raise ValueError('LOCAL_CUSTODY_DIRECT_TRADE_ENTITLEMENT')
    if expected_result.get('enchanted') and (before_assets is not None or after_assets is not None):
        if not isinstance(before_assets, dict) or not isinstance(after_assets, dict):
            raise ValueError('LOCAL_CUSTODY_DIRECT_TRADE_ENTITLEMENT')
        old_offer = before_shared.get('direct_trades', {}).get(request['row']['id'])
        enchant.credit(before_assets, after_assets, before_characters, characters, old_offer)


class DirectTradeStoreMixin:
    def direct_trade_action(self, issuer, sequence, row, *, catalog, now=None, expected_revision=None, gear_tables=None):
        op = _request(row); c = _custody(); request = copy.deepcopy(row)
        selected = sorted((row['owner'], row['recipient'])) if op == 'TradeAccept' else []
        if expected_revision is not None and issuer not in selected:
            selected.append(issuer)
        expected = {} if expected_revision is None else {issuer: expected_revision}
        moment = c.clock(time.time() if now is None else now)

        def transform(payloads, shared):
            characters = {key: self._character(key) for key in self._roster()}
            for key, payload in payloads.items():
                characters[key]['payload'] = payload
            names = {r['id']: r['name'] for r in self._read('characters.json', c.MAX_BYTES)['characters']}
            return apply(characters, shared, issuer, sequence, request, now=moment, catalog=catalog,
                         names=names, gear_tables=gear_tables)

        return self.transact(issuer, sequence, dict(op='DIRECT_TRADE_ACTION', row=request), selected, transform,
                             expected_revisions=expected)


class SharedLocalDirectTradeMixin:
    def _shared_direct_trade_command_locked(self, row, snapshot, *, _cursor=False):
        """Explicit selector keeps saved-character handoffs out of NPC barter."""
        if not _cursor:
            cursor_result = enchant.cursor_command(self, row, snapshot)
            if cursor_result is not None:return cursor_result
        if 'shared_trade' in row and type(row['shared_trade']) is not bool:
            raise ValueError('DIRECT_TRADE_SELECTOR_INVALID')
        if row.get('shared_trade') is not True:
            if snapshot and row.get('op') == 'TradeOpen' and find(snapshot['shared'], self._local_character_id):
                raise ValueError('SERVICE_OTHER_OFFER_PENDING')
            return None
        if snapshot is None:
            raise ValueError('DIRECT_TRADE_SAVED_CHARACTER_REQUIRED')
        if row.get('session') != self._service_generation:
            raise ValueError('SERVICE_WINDOW_CHANGED_OR_CLOSED')
        original_op = row.get('op'); op = {'TradeBegin': 'TradeJoin', 'TradeClose': 'TradeCancel'}.get(original_op, original_op)
        if op == 'TradeTarget':
            raise ValueError('DIRECT_TRADE_SAVED_ITEMS_ONLY')
        if op == 'TradeConfirmChanged':
            raise ValueError('TRADE_OFFER_CHANGED_ACCEPT_AGAIN')
        character = self._local_character_id
        if op == 'TradeOpen':
            if self._service_trade or self._services.get('petition_offer'):
                raise ValueError('SERVICE_OTHER_OFFER_PENDING')
            target = self._shared_person_locked(row.get('target'), snapshot)
            if target is None:
                raise ValueError('DIRECT_TRADE_OTHER_CHARACTER_REQUIRED')
            request = dict(op=op, target=target)
        else:
            request = dict(op=op, **{key: copy.deepcopy(row.get('shared_trade_' + key)) for key in CONTEXT})
            if op in ('TradeSet', 'TradeClear'):
                request['slot'] = row.get('slot')
            if op == 'TradeSet':
                request['item'] = copy.deepcopy(row.get('shared_trade_item'))
                if not isinstance(request['item'], dict) or row.get('item') != request['item'].get('instance'):
                    raise ValueError('DIRECT_TRADE_SHOWN_ITEM_CHANGED')
            if op == 'TradeMoney':
                request['money'] = row.get('money')
            if op == 'TradeEnchant':
                request.update(scroll=copy.deepcopy(row.get('shared_trade_scroll')), enchant_id=row.get('enchant_id'),
                               replace=row.get('replace', False), bind=row.get('bind', False))
                if not isinstance(request['scroll'], dict) or row.get('scroll') != request['scroll'].get('instance'):
                    raise ValueError('DIRECT_TRADE_SHOWN_SCROLL_CHANGED')
            _request(request)
        prior = snapshot['shared']['receipts'].get(character + ':' + str(row.get('custody_sequence', '')))
        replay = bool(prior and prior['request'].get('op') == 'DIRECT_TRADE_ACTION')
        if op != 'TradeCancel':
            if self._player_defeated_locked():
                raise ValueError('PLAYER_DEFEATED')
            if self._services['taxi_flight']:
                raise ValueError('TAXI_IN_PROGRESS')
        if op == 'TradeSet' and not replay:
            actual = self._item_instance_locked(request['item']['instance'])
            if self._item_binding_locked(actual):
                raise ValueError('ITEM_PENDING_CONFIRMATION')
            payload = dict(item_instances=list(self._item_instances.values()))
            if request['slot'] == 7:
                enchant.target_item(payload, character, request['item'], self._item_catalog, gear_tables=self._gear_tables)
            else:_reference_item(payload, character, request['item'], self._item_catalog)
        if op == 'TradeEnchant' and not replay:
            actual = self._item_instance_locked(request['scroll']['instance'])
            pending = enchant.other_pending(self, actual) if _cursor else self._item_binding_locked(actual)
            if pending:
                raise ValueError('ITEM_PENDING_CONFIRMATION')
            enchant.scroll_item(dict(item_instances=list(self._item_instances.values())), character,
                                request['scroll'], self._item_catalog)
        if op == 'TradeAccept' and not replay:
            offer = find(snapshot['shared'], character)
            if offer:
                own_side = offer['sides'][character]
                pinned = list(own_side['slots'].values()) + [own_side.get('enchant_target'),
                    (own_side.get('enchant_service') or {}).get('scroll')]
                if any(ref and self._item_binding_locked(self._item_instance_locked(ref['instance'])) for ref in pinned):
                    raise ValueError('ITEM_PENDING_CONFIRMATION')
        result = self._shared_execute_locked(row, lambda store, owner, seq, revision:
            store.direct_trade_action(owner, seq, request, catalog=self._item_catalog, expected_revision=revision,
                                      gear_tables=self._gear_tables))
        if result.get('replayed'):
            return []
        if op in ('TradeOpen', 'TradeJoin'):
            self._service_generation += 1
        if result['result'].get('completed') or op == 'TradeCancel':
            self._service_windows['trade'] = False
            if isinstance(self._item_target, dict) and 'shared_trade_request' in self._item_target:
                self._clear_item_targeting_locked()
            return ([dict(event='BAG_UPDATE', args=[0]), dict(event='PLAYER_MONEY', args=[])]
                    if result['result'].get('completed') else []) + ([dict(event='UNIT_INVENTORY_CHANGED', args=['player'])]
                    if result['result'].get('enchanted') else []) + [dict(event='TRADE_CLOSED', args=[])]
        if op in ('TradeOpen', 'TradeJoin'):
            return [dict(event='TRADE_SHOW', args=[])]
        if op in ('TradeSet', 'TradeClear'):
            return [dict(event='TRADE_PLAYER_ITEM_CHANGED', args=[request['slot']]), dict(event='TRADE_ACCEPT_UPDATE', args=[0, 0])]
        if op in ('TradeEnchant', 'TradeEnchantClear'):
            return [dict(event='TRADE_TARGET_ITEM_CHANGED', args=[7]), dict(event='TRADE_ACCEPT_UPDATE', args=[0, 0])]
        if op == 'TradeMoney':
            return [dict(event='TRADE_MONEY_CHANGED', args=[]), dict(event='TRADE_ACCEPT_UPDATE', args=[0, 0])]
        offer = find(self._shared_custody_locked()['shared'], character)
        other = offer['recipient'] if offer['owner'] == character else offer['owner']
        return [dict(event='TRADE_ACCEPT_UPDATE', args=[int(bool(offer['accepts'][character])), int(bool(offer['accepts'][other]))])]

    def _shared_direct_trade_view_locked(self, value, snapshot):
        character = self._local_character_id; offer = find(snapshot['shared'], character)
        if offer is None:
            return value
        now = max(snapshot['shared']['clock'], self._services['clock'], time.time())
        if offer['expires'] <= now:
            return value
        other = offer['recipient'] if offer['owner'] == character else offer['owner']
        rows = copy.deepcopy(snapshot.get('direct_trade_items', {}).get(offer['id'], {}))
        # Active rows come from the one actual runtime; other rows are bounded
        # saved custody metadata, never fabricated visible characters.
        own = {}
        for slot, ref in offer['sides'][character]['slots'].items():
            try:
                own[slot] = _reference_item(dict(item_instances=list(self._item_instances.values())), character, ref)
            except ValueError:
                own[slot] = None
        own_target = offer['sides'][character].get('enchant_target')
        if own_target:
            try:own['7'] = enchant.target_item(dict(item_instances=list(self._item_instances.values())), character, own_target)
            except ValueError:own['7'] = None
        inventory_references = {}
        gear_references = {}; gear_items = []; scroll_references = {}; scroll_rows = []
        payload = dict(item_instances=list(self._item_instances.values()))
        for item in self._item_instances.values():
            if item.get('owner_id') == 'player' and item.get('location') == 'INVENTORY':
                try:
                    inventory_references[item['instance_id']] = reference(payload, character, item['instance_id'], self._item_catalog)
                except ValueError:
                    pass
                if item.get('scroll_enchant_id'):
                    definition = enchants.definition(item['scroll_enchant_id'])
                    if definition and len(scroll_rows) < 32:
                        try:ref = enchant.scroll_reference(payload, character, item['instance_id'], self._item_catalog)
                        except ValueError:continue
                        scroll_references[item['instance_id']] = copy.deepcopy(ref)
                        scroll_rows.append(dict(id=item['instance_id'], instance_id=item['instance_id'],
                            enchant_id=definition['id'], name=definition['name'], quantity=item['quantity'],
                            required_level=definition['required_level'], binds=definition.get('binds') is True,
                            reference=copy.deepcopy(ref)))
            if item.get('owner_id') == 'player' and item.get('location') in ('INVENTORY', 'EQUIPPED') and item.get('gear'):
                try:
                    if self._item_binding_locked(item):continue
                    gear_references[item['instance_id']] = enchant.target_reference(payload, character, item['instance_id'],
                        self._item_catalog, gear_tables=self._gear_tables)
                    gear_items.append(items.instance_view(self._item_catalog, item, sim_time=self._sim_time))
                except ValueError:pass
        roster = {r['id']: r for r in snapshot['roster']}
        from backend.game_engine_adapter_identity import identity as character_identity
        selection = roster[other].get('selection', {})
        labels = character_identity(dict(character_creation=dict(active=bool(selection), selection=selection), progression={}))
        cls = labels.get('class') or {}
        target_profile = dict(id=other, name=roster[other]['name'], level=roster[other].get('level', 1),
            class_name=cls.get('name', ''), class_file=cls.get('file', ''), online=False,
            guid=self._shared_group_guids_locked(snapshot)[other])
        def view(item):
            return items.instance_view(self._item_catalog, item, sim_time=self._sim_time) if item else None
        own_service = rows.get(character, {}).get('enchant_service')
        other_service = rows.get(other, {}).get('enchant_service')
        own_rows = {slot: view(item) for slot, item in own.items()}
        target_rows = [view(rows.get(other, {}).get(str(slot))) for slot in range(1, MAX_SLOTS + 1)]
        if any(set(side) == enchant.SIDE_FIELDS for side in offer['sides'].values()):
            target_rows.append(view(rows.get(other, {}).get('7')))
        if own_rows.get('7'):own_rows['7']['enchantment'] = (other_service or {}).get('name', '')
        if len(target_rows) > 6 and target_rows[6]:target_rows[6]['enchantment'] = (own_service or {}).get('name', '')
        slots = {slot: ref['instance'] for slot, ref in offer['sides'][character]['slots'].items()}
        if own_target:slots['7'] = own_target['instance']
        value['trade'] = dict(open=offer['owner'] == character or offer['joined'],
            pending=offer['recipient'] == character and not offer['joined'], target=other,
            target_name=roster[other]['name'], shared_trade=True,
            target_profile=target_profile,
            **{'shared_trade_' + key: copy.deepcopy(offer[key]) for key in CONTEXT},
            slots=slots,
            item_references=copy.deepcopy(offer['sides'][character]['slots']),
            inventory_references=inventory_references,
            gear_references=gear_references, gear_items=gear_items, scroll_references=scroll_references,
            enchant_scrolls=scroll_rows, enchant_target_reference=copy.deepcopy(own_target),
            target_enchant_target_reference=copy.deepcopy(offer['sides'][other].get('enchant_target')),
            enchant_service=copy.deepcopy(own_service), target_enchant_service=copy.deepcopy(other_service),
            money=offer['sides'][character]['copper'], target_money=offer['sides'][other]['copper'],
            offer_revision=offer['revision'], player_accepted=bool(offer['accepts'][character]),
            target_accepted=bool(offer['accepts'][other]), expires=offer['expires'], stock=[],
            player_rows=own_rows, target_rows=target_rows)
        enchant.cursor_view(self, value)
        return value
