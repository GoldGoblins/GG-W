"""Exact, non-transferred gear services for two consenting saved characters.

This leaf never publishes a save or relaxes custody conservation.  The trade
state machine calls it before its existing two-character journal commits.  Its
recovery calculation uses the immutable original gear and authored recipe;
neither a client preview nor a client-supplied gear table is authority.
"""
from __future__ import annotations

import copy
import math

from backend import game_engine_enchants as enchants, game_engine_gear as gear
from backend import game_engine_items as items

TARGET_FIELDS = {'asset', 'instance', 'quantity', 'location', 'slot', 'equipped_slot',
                 'item_hash', 'definition_hash'}
SERVICE_FIELDS = {'target', 'scroll', 'enchant_id', 'recipe_hash', 'replace', 'bind'}
LEGACY_SIDE_FIELDS = {'slots', 'copper'}
SIDE_FIELDS = LEGACY_SIDE_FIELDS | {'enchant_target', 'enchant_service'}


def _modules():
    from backend import game_engine_local_custody as custody
    from backend import game_engine_local_direct_trade as direct
    return custody, direct


def _physical(payload, instance):
    matches = [row for row in payload.get('item_instances', [])
               if isinstance(row, dict) and row.get('instance_id') == instance]
    if len(matches) != 1:
        raise ValueError('DIRECT_TRADE_ENCHANT_ITEM_CHANGED')
    return matches[0]


def _policy(item, owner, catalog=None):
    c, _ = _modules(); c.identity(owner)
    c.integer(item.get('quantity'), 1, 1)
    if (item.get('owner_id') != 'player' or item.get('location') not in ('INVENTORY', 'EQUIPPED')
            or item.get('quantity') != 1 or not isinstance(item.get('gear'), dict)
            or item.get('kind') in ('QUEST', 'CONTAINER') or item.get('contents')
            or item.get('definition_id') == 'item.gg_wrapped_gift' or 'gift' in item
            or item.get('gift_invalid') or item.get('gift_quarantine')):
        raise ValueError('DIRECT_TRADE_ENCHANT_OWNED_GEAR_REQUIRED')
    if item.get('bound_to') and item['bound_to'] != owner:
        raise ValueError('DIRECT_TRADE_ENCHANT_OWNER_CHANGED')
    if item['location'] == 'INVENTORY':
        c.integer(item.get('slot_index'), 0, items.MAX_INVENTORY_SLOTS - 1)
        if item.get('equipped_slot'):
            raise ValueError('DIRECT_TRADE_ENCHANT_LOCATION_CHANGED')
    elif not c.short_text(item.get('equipped_slot'), 32):
        raise ValueError('DIRECT_TRADE_ENCHANT_LOCATION_CHANGED')
    else:
        c.integer(item.get('slot_index', -1), -1, items.MAX_INVENTORY_SLOTS - 1)
    state = item['gear']
    rows = state.get('enchantments')
    if (not isinstance(rows, list) or len(rows) > gear.MAX_ENCHANTMENTS
            or not isinstance(state.get('stats'), dict) or not isinstance(state.get('base_stats'), dict)
            or not isinstance(state.get('modifiers'), list)):
        raise ValueError('DIRECT_TRADE_ENCHANT_GEAR_INVALID')
    for row in rows + state['modifiers']:
        if (not isinstance(row, dict) or not isinstance(row.get('stat'), str)
                or len(row['stat']) > 48 or type(row.get('value')) not in (int, float)
                or not math.isfinite(row['value']) or abs(row['value']) > 100000):
            raise ValueError('DIRECT_TRADE_ENCHANT_GEAR_INVALID')
    # Saved derived contributions must be bounded numbers, not strings/bools.
    for stats in (state['stats'], state['base_stats']):
        for key, value in stats.items():
            if (not isinstance(key, str) or not key or len(key) > 48
                    or type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 100000):
                raise ValueError('DIRECT_TRADE_ENCHANT_GEAR_INVALID')
    if catalog is None:
        return None
    definition = items.definition(catalog, item.get('definition_id'))
    if not definition or definition.get('kind') in ('QUEST', 'CONTAINER'):
        raise ValueError('DIRECT_TRADE_ENCHANT_DEFINITION_INVALID')
    # NO_TRADE/bonding restrict transfers, not a service on the real owner's gear.
    return dict(id=definition['id'], kind=definition.get('kind', 'ITEM'),
                tags=copy.deepcopy(definition.get('tags', [])), bonding=definition.get('bonding', 0),
                stack_limit=definition.get('stack_limit', 1), equip_slot=definition.get('equip_slot', ''))


def target_reference(payload, owner, instance, catalog, *, gear_tables=None):
    c, direct = _modules()
    item = _physical(payload, instance); policy = _policy(item, owner, catalog)
    if gear_tables is not None:
        _current_gear(item['gear'], gear_tables)
    return dict(asset=c.asset_id(owner, item), instance=instance, quantity=1,
                location=item['location'], slot=item.get('slot_index', -1),
                equipped_slot=item.get('equipped_slot', ''), item_hash=direct._item_hash(item),
                definition_hash=c.digest(policy))


def target_item(payload, owner, ref, catalog=None, *, gear_tables=None):
    c, direct = _modules()
    if not isinstance(ref, dict) or set(ref) != TARGET_FIELDS:
        raise ValueError('DIRECT_TRADE_ENCHANT_REFERENCE_INVALID')
    c.short_text(ref['instance'], 64); c.integer(ref['quantity'], 1, 1)
    c.integer(ref['slot'], -1, items.MAX_INVENTORY_SLOTS - 1)
    c.short_text(ref['equipped_slot'], 32)
    c.LocalCustodyStore._hash(ref['item_hash']); c.LocalCustodyStore._hash(ref['definition_hash'])
    item = _physical(payload, ref['instance']); policy = _policy(item, owner, catalog)
    if (c.asset_id(owner, item) != ref['asset'] or direct._item_hash(item) != ref['item_hash']
            or item['location'] != ref['location'] or item.get('slot_index', -1) != ref['slot']
            or item.get('equipped_slot', '') != ref['equipped_slot']):
        raise ValueError('DIRECT_TRADE_ENCHANT_ITEM_CHANGED')
    if catalog is not None and c.digest(policy) != ref['definition_hash']:
        raise ValueError('DIRECT_TRADE_ENCHANT_DEFINITION_CHANGED')
    if gear_tables is not None:
        _current_gear(item['gear'], gear_tables)
    return item


def _scroll_policy(item, owner, catalog=None):
    c, _ = _modules(); c.identity(owner)
    if (item.get('owner_id') != 'player' or item.get('location') != 'INVENTORY'
            or item.get('definition_id') != 'item.enchant_scroll' or item.get('kind') != 'SCROLL'
            or item.get('contents') or any(key in item for key in ('gift', 'gift_quarantine'))):
        raise ValueError('ENCHANT_SCROLL_REQUIRED')
    if item.get('bound_to') and item['bound_to'] != owner:
        raise ValueError('DIRECT_TRADE_ENCHANT_OWNER_CHANGED')
    c.integer(item.get('quantity'), 1, 999)
    c.integer(item.get('slot_index'), 0, items.MAX_INVENTORY_SLOTS - 1)
    if catalog is None:
        return None
    definition = items.definition(catalog, item['definition_id'])
    if not definition or definition.get('kind') != 'SCROLL':
        raise ValueError('ENCHANT_SCROLL_REQUIRED')
    tags = definition.get('tags', [])
    if not isinstance(tags, (list, tuple)) or any(not isinstance(tag, str) for tag in tags):
        raise ValueError('DIRECT_TRADE_DEFINITION_INVALID')
    bonding = c.integer(definition.get('bonding', 0), 0, 5)
    limit = c.integer(definition.get('stack_limit', 1), 1, 999)
    if item['quantity'] > limit:
        raise ValueError('DIRECT_TRADE_STACK_INVALID')
    # Identical to the ordinary reference digest for unbound normal scrolls;
    # NO_TRADE/bonding stay pinned, but consumption is not a transfer.
    return [dict(id=definition['id'], kind=definition['kind'], tags=sorted(tags),
                 bonding=bonding, stack_limit=limit)]


def scroll_reference(payload, owner, instance, catalog):
    c, direct = _modules(); item = _physical(payload, instance)
    policy = _scroll_policy(item, owner, catalog)
    return dict(asset=c.asset_id(owner, item), instance=instance, quantity=item['quantity'],
                slot=item['slot_index'], item_hash=direct._item_hash(item), definition_hash=c.digest(policy))


def scroll_item(payload, owner, ref, catalog=None):
    c, direct = _modules()
    if not isinstance(ref, dict) or set(ref) != direct.REFERENCE_FIELDS:
        raise ValueError('DIRECT_TRADE_REFERENCE_INVALID')
    c.short_text(ref['instance'], 64); c.integer(ref['quantity'], 1, 999)
    c.integer(ref['slot'], 0, items.MAX_INVENTORY_SLOTS - 1)
    c.LocalCustodyStore._hash(ref['item_hash']); c.LocalCustodyStore._hash(ref['definition_hash'])
    item = _physical(payload, ref['instance']); policy = _scroll_policy(item, owner, catalog)
    if (item['quantity'] != ref['quantity'] or item['slot_index'] != ref['slot']
            or c.asset_id(owner, item) != ref['asset'] or direct._item_hash(item) != ref['item_hash']):
        raise ValueError('DIRECT_TRADE_ITEM_CHANGED')
    if catalog is not None and c.digest(policy) != ref['definition_hash']:
        raise ValueError('DIRECT_TRADE_DEFINITION_CHANGED')
    return item


def _current_gear(state, tables):
    normalized = gear.recalculate_gear(copy.deepcopy(state), tables)
    # Original permanent-slot replacement reorders enchant rows after its stat
    # calculation; its enchant modifier ordering need not match that row order.
    if ({key: value for key, value in normalized.items() if key != 'modifiers'}
            != {key: value for key, value in state.items() if key != 'modifiers'}
            or [row for row in normalized['modifiers'] if row.get('source') != 'ENCHANT']
            != [row for row in state['modifiers'] if row.get('source') != 'ENCHANT']):
        raise ValueError('DIRECT_TRADE_ENCHANT_GEAR_CHANGED')


def canonical_gear(item, definition, *, replace=False, gear_tables=None):
    """Preserve physical socket/runeword contributions; alter only the enchant.

    The before-save already owns its socket/runeword stats.  Their existing
    contribution is retained exactly, while enchant rows come from the actual
    authored apply_enchant implementation.  Live callers compare the result
    against the full current runtime tables before it can become an offer.
    """
    if type(replace) is not bool:
        raise ValueError('DIRECT_TRADE_ENCHANT_CONFIRMATION_INVALID')
    original = item['gear']; working = copy.deepcopy(original)
    if replace and working['enchantments']:
        working['enchantments'].pop(0)
    # This scratch result supplies canonical rows, metadata and category checks.
    # Its socket recalculation is discarded, preserving actual custom sockets.
    ok, result = gear.apply_enchant(working, definition['id'],
                                   dict(enchantments={definition['id']: definition}))
    if not ok:
        raise ValueError(result['error'])
    calculation_rows = copy.deepcopy(working['enchantments'])
    if replace:
        working['enchantments'].insert(0, working['enchantments'].pop())
    after = copy.deepcopy(original); after['enchantments'] = working['enchantments']
    stats = copy.deepcopy(original['stats'])
    non_enchant_keys = set(original['base_stats']) | {
        row.get('stat') for row in original['modifiers'] if row.get('source') != 'ENCHANT'}
    for row in original['enchantments']:
        gear._add_stat(stats, row.get('stat'), -gear._safe_float(row.get('value', 1)))
    # Removing a unique enchant contribution removes its derived stat key too.
    new_keys = {row.get('stat') for row in after['enchantments']}
    for row in original['enchantments']:
        key = row.get('stat')
        if key not in non_enchant_keys and key not in new_keys and stats.get(key) == 0:
            stats.pop(key, None)
    for row in calculation_rows:
        gear._add_stat(stats, row.get('stat'), row.get('value', 1))
    after['stats'] = stats
    after['modifiers'] = ([copy.deepcopy(row) for row in original['modifiers'] if row.get('source') != 'ENCHANT']
        + [gear._modifier_row('ENCHANT', row['id'], row['stat'], row['value'])
           for row in calculation_rows])[:gear.MAX_GEAR_MODIFIERS]
    if gear_tables is not None:
        actual = copy.deepcopy(original)
        if replace and actual['enchantments']:
            actual['enchantments'].pop(0)
        tables = dict(gear_tables, enchantments=dict(gear_tables.get('enchantments', {}),
                      **{definition['id']: definition}))
        ok, result = gear.apply_enchant(actual, definition['id'], tables)
        if not ok:
            raise ValueError(result['error'])
        if replace:
            actual['enchantments'].insert(0, actual['enchantments'].pop())
        if actual != after:
            raise ValueError('DIRECT_TRADE_ENCHANT_GEAR_CHANGED')
    return after


def other(offer, issuer):
    return offer['recipient'] if offer['owner'] == issuer else offer['owner']


def extended(side):
    if set(side) == LEGACY_SIDE_FIELDS:
        side.update(enchant_target=None, enchant_service=None)
    return side


def selected(offer):
    return any(side.get('enchant_target') or side.get('enchant_service') for side in offer['sides'].values())


def set_target(characters, offer, issuer, ref, catalog=None, *, gear_tables=None):
    _, direct = _modules()
    target_item(characters[issuer]['payload'], issuer, ref, catalog, gear_tables=gear_tables)
    side = offer['sides'][issuer]
    if any(value['asset'] == ref['asset'] for value in side['slots'].values()):
        raise ValueError('DIRECT_TRADE_ITEM_ALREADY_OFFERED')
    extended(side)['enchant_target'] = copy.deepcopy(ref)
    extended(offer['sides'][other(offer, issuer)])['enchant_service'] = None


def clear_target(offer, issuer):
    extended(offer['sides'][issuer])['enchant_target'] = None
    extended(offer['sides'][other(offer, issuer)])['enchant_service'] = None


def _service(characters, offer, issuer, service, catalog=None, *, gear_tables=None):
    c, direct = _modules(); target_owner = other(offer, issuer)
    if not isinstance(service, dict) or set(service) != SERVICE_FIELDS:
        raise ValueError('DIRECT_TRADE_ENCHANT_SERVICE_INVALID')
    if type(service['replace']) is not bool or type(service['bind']) is not bool:
        raise ValueError('DIRECT_TRADE_ENCHANT_CONFIRMATION_INVALID')
    ref = offer['sides'][target_owner].get('enchant_target')
    if not ref or service['target'] != ref['asset']:
        raise ValueError('DIRECT_TRADE_ENCHANT_TARGET_CHANGED')
    target = target_item(characters[target_owner]['payload'], target_owner, ref, catalog, gear_tables=gear_tables)
    scroll = scroll_item(characters[issuer]['payload'], issuer, service['scroll'], catalog)
    if not isinstance(service['enchant_id'], str) or not service['enchant_id'] or len(service['enchant_id']) > 96:
        raise ValueError('DIRECT_TRADE_ENCHANT_RECIPE_CHANGED')
    definition = enchants.definition(service['enchant_id'])
    if (not definition or scroll.get('scroll_enchant_id') != definition['id']
            or definition['id'] != service['enchant_id'] or c.digest(definition) != service['recipe_hash']):
        raise ValueError('DIRECT_TRADE_ENCHANT_RECIPE_CHANGED')
    if characters[issuer]['payload'].get('progression', {}).get('level', 1) < definition['required_level']:
        raise ValueError('ENCHANT_LEVEL_REQUIRED')
    binding = definition.get('binds') is True and not target.get('bound_to')
    if service['bind'] != binding:
        raise ValueError('DIRECT_TRADE_ENCHANT_BIND_CONFIRMATION_REQUIRED')
    if service['replace'] != bool(target['gear']['enchantments']):
        raise ValueError('DIRECT_TRADE_ENCHANT_REPLACE_CONFIRMATION_REQUIRED')
    side = offer['sides'][issuer]
    if any(value['asset'] == service['scroll']['asset'] for value in side['slots'].values()):
        raise ValueError('DIRECT_TRADE_ITEM_ALREADY_OFFERED')
    return target_owner, target, scroll, definition, canonical_gear(target, definition,
        replace=service['replace'], gear_tables=gear_tables)


def service_reference(characters, offer, issuer, scroll_ref, enchant_id, catalog=None,
                      *, replace=False, bind=False, gear_tables=None):
    c, _ = _modules(); ref = offer['sides'][other(offer, issuer)].get('enchant_target')
    definition = enchants.definition(enchant_id) if isinstance(enchant_id, str) else None
    if not ref or not definition:
        raise ValueError('TRADE_ENCHANT_TARGET_AND_RECIPE_REQUIRED')
    service = dict(target=ref['asset'], scroll=copy.deepcopy(scroll_ref), enchant_id=definition['id'],
                   recipe_hash=c.digest(definition), replace=replace, bind=bind)
    _service(characters, offer, issuer, service, catalog, gear_tables=gear_tables)
    return service


def set_service(characters, offer, issuer, service, catalog=None, *, gear_tables=None):
    _service(characters, offer, issuer, service, catalog, gear_tables=gear_tables)
    extended(offer['sides'][issuer])['enchant_service'] = copy.deepcopy(service)


def validate(characters, offer, catalog=None, *, gear_tables=None):
    for issuer, side in offer['sides'].items():
        if set(side) not in (LEGACY_SIDE_FIELDS, SIDE_FIELDS):
            raise ValueError('DIRECT_TRADE_RECORD_INVALID')
        ref = side.get('enchant_target')
        if ref is not None:
            target_item(characters[issuer]['payload'], issuer, ref, catalog, gear_tables=gear_tables)
            if any(value['asset'] == ref['asset'] for value in side['slots'].values()):
                raise ValueError('DIRECT_TRADE_ITEM_ALREADY_OFFERED')
        service = side.get('enchant_service')
        if service is not None:
            _service(characters, offer, issuer, service, catalog, gear_tables=gear_tables)


def complete(characters, offer, catalog=None, *, gear_tables=None):
    """Consume one pinned scroll per service and retain the target's custody."""
    _, direct = _modules()
    if (not offer.get('joined') or set(offer.get('accepts', {})) != {offer['owner'], offer['recipient']}
            or any(value != direct.terms(offer) for value in offer['accepts'].values())):
        raise ValueError('DIRECT_TRADE_RECIPIENT_CONSENT_REQUIRED')
    validate(characters, offer, catalog, gear_tables=gear_tables)
    jobs = [(issuer, _service(characters, offer, issuer, side['enchant_service'], catalog,
                             gear_tables=gear_tables)) for issuer, side in offer['sides'].items()
            if side.get('enchant_service')]
    result = []
    for issuer, (target_owner, target, scroll, definition, after) in jobs:
        service = offer['sides'][issuer]['enchant_service']
        target['gear'] = after
        if service['bind']:
            target['bound_to'] = target_owner
        if scroll['quantity'] == 1:
            characters[issuer]['payload']['item_instances'].remove(scroll)
        else:
            scroll['quantity'] -= 1
        result.append(dict(owner=target_owner, target=target['instance_id'], provider=issuer,
                           scroll=scroll['instance_id'], enchant_id=definition['id']))
    for issuer, _ in jobs:
        _modules()[0].LocalCustodyStore._sync_inventory(characters[issuer]['payload'])
    return result


def credit(before_assets, after_assets, before_characters, characters, offer):
    """Called only AFTER the full deterministic entitlement proof succeeds.

    Exactly one gear hash and one scroll decrement/removal per accepted service
    are credited.  The store still compares every other physical asset/money.
    """
    c, direct = _modules()
    for issuer, side in offer['sides'].items():
        service = side.get('enchant_service')
        if not service:
            continue
        target_owner = other(offer, issuer)
        target_before = target_item(before_characters[target_owner]['payload'], target_owner,
                                   offer['sides'][target_owner]['enchant_target'])
        scroll_before = scroll_item(before_characters[issuer]['payload'], issuer, service['scroll'])
        for owner, physical in ((target_owner, target_before), (issuer, scroll_before)):
            key = c.asset_id(owner, physical)
            if key not in before_assets:
                raise ValueError('LOCAL_CUSTODY_DIRECT_TRADE_ENTITLEMENT')
            current = [row for row in characters[owner]['payload']['item_instances']
                       if c.asset_id(owner, row) == key]
            if len(current) == 1:
                before_assets[key] = direct._item_hash(current[0])
                if after_assets.get(key) != before_assets[key]:
                    raise ValueError('LOCAL_CUSTODY_DIRECT_TRADE_ENTITLEMENT')
            elif not current and physical is scroll_before and physical['quantity'] == 1 and key not in after_assets:
                del before_assets[key]
            else:
                raise ValueError('LOCAL_CUSTODY_DIRECT_TRADE_ENTITLEMENT')


def service_view(characters, offer, issuer):
    service = offer['sides'][issuer].get('enchant_service')
    if not service:
        return None
    owner, target, scroll, definition, preview = _service(characters, offer, issuer, service)
    old = target['gear']['enchantments'][0] if target['gear']['enchantments'] else None
    return dict(provider=issuer, owner=owner, target=target['instance_id'], scroll=scroll['instance_id'],
                quantity=1, enchant_id=definition['id'], name=definition['name'],
                required_level=definition['required_level'], replace=service['replace'], bind=service['bind'],
                old_enchant=old.get('name', '') if old and service['replace'] else '',
                preview=copy.deepcopy(preview))


def _cursor_characters(host, snapshot, offer, issuer):
    target_owner = other(offer, issuer)
    row = snapshot.get('direct_trade_items', {}).get(offer['id'], {}).get(target_owner, {}).get('7')
    if not row:
        raise ValueError('DIRECT_TRADE_ENCHANT_TARGET_CHANGED')
    return {issuer: dict(payload=dict(item_instances=list(host._item_instances.values()),
                                      progression=host._progression)),
            target_owner: dict(payload=dict(item_instances=[copy.deepcopy(row)]))}


def other_pending(host, item):
    """Exclude only this actual targeting cursor from existing pending guards."""
    record = host._item_target
    try:
        host._item_target = None
        return host._item_binding_locked(item)
    finally:
        host._item_target = record


def cursor_command(host, row, snapshot):
    """Original target-slot cursor and prompts, with no early asset mutation."""
    c, direct = _modules(); op = row.get('op'); record = host._item_target
    marked = isinstance(record, dict) and 'shared_trade_request' in record
    if op != 'TradeEnchantPick' and not (marked and op in ('EnchantBindConfirm', 'EnchantReplaceConfirm', 'EnchantCancel')):
        return None
    if snapshot is None or row.get('target_generation') != host._item_target_generation:
        raise ValueError('ENCHANT_CURSOR_CHANGED')
    if op == 'EnchantCancel':
        host._clear_item_targeting_locked(); return []
    if host._player_defeated_locked():
        raise ValueError('PLAYER_DEFEATED')
    if host._services['taxi_flight']:
        raise ValueError('TAXI_IN_PROGRESS')
    issuer = host._local_character_id; offer = direct.find(snapshot['shared'], issuer)
    if not offer:
        raise ValueError('DIRECT_TRADE_OFFER_CHANGED_OR_EXPIRED')
    record, scroll, definition = host._enchant_source_locked()
    if other_pending(host, scroll):
        raise ValueError('ITEM_PENDING_CONFIRMATION')
    if op == 'TradeEnchantPick':
        if row.get('shared_trade') is not True or row.get('session') != host._service_generation:
            raise ValueError('SERVICE_WINDOW_CHANGED_OR_CLOSED')
        if row.get('slot') != 7 or record['stage'] != 'SELECT':
            raise ValueError('ENCHANT_CONFIRMATION_CHANGED')
        if any(row.get('shared_trade_' + key) != offer[key] for key in direct.CONTEXT):
            raise ValueError('DIRECT_TRADE_OFFER_CHANGED_OR_EXPIRED')
        target_ref = offer['sides'][other(offer, issuer)].get('enchant_target')
        if not target_ref or row.get('shared_trade_target') != target_ref:
            raise ValueError('DIRECT_TRADE_ENCHANT_TARGET_CHANGED')
        request = dict(kind='service', op='TradeEnchant', shared_trade=True,
                       session=host._service_generation, enchant_id=definition['id'], scroll=scroll['instance_id'],
                       shared_trade_scroll=copy.deepcopy(row.get('shared_trade_scroll')),
                       **{'shared_trade_' + key: copy.deepcopy(offer[key]) for key in direct.CONTEXT})
        characters = _cursor_characters(host, snapshot, offer, issuer)
        target = target_item(characters[other(offer, issuer)]['payload'], other(offer, issuer), target_ref,
                             host._item_catalog, gear_tables=host._gear_tables)
        request['replace'] = bool(target['gear']['enchantments'])
        request['bind'] = definition.get('binds') is True and not target.get('bound_to')
        service_reference(characters, offer, issuer, request['shared_trade_scroll'], definition['id'],
                          host._item_catalog, replace=request['replace'], bind=request['bind'], gear_tables=host._gear_tables)
        host._item_target_generation += 1
        record.update(shared_trade_request=request, shared_trade_target=copy.deepcopy(target_ref),
                      bind_confirmed=False, replace_confirmed=False)
    else:
        request = record['shared_trade_request']
        if (request['session'] != host._service_generation
                or any(request.get('shared_trade_' + key) != offer[key] for key in direct.CONTEXT)
                or offer['sides'][other(offer, issuer)].get('enchant_target') != record['shared_trade_target']
                or request['scroll'] != scroll['instance_id']):
            raise ValueError('DIRECT_TRADE_OFFER_CHANGED_OR_EXPIRED')
        if op == 'EnchantBindConfirm' and record['stage'] == 'BIND':record['bind_confirmed'] = True
        elif op == 'EnchantReplaceConfirm' and record['stage'] == 'REPLACE':record['replace_confirmed'] = True
        else:raise ValueError('ENCHANT_CONFIRMATION_CHANGED')
    request = record['shared_trade_request']; characters = _cursor_characters(host, snapshot, offer, issuer)
    target = target_item(characters[other(offer, issuer)]['payload'], other(offer, issuer), record['shared_trade_target'],
                         host._item_catalog, gear_tables=host._gear_tables)
    service_reference(characters, offer, issuer, request['shared_trade_scroll'], request['enchant_id'],
                      host._item_catalog, replace=request['replace'], bind=request['bind'], gear_tables=host._gear_tables)
    if request['bind'] and not record['bind_confirmed']:
        record['stage'] = 'BIND'; return [dict(event='BIND_ENCHANT', args=[])]
    if request['replace'] and not record['replace_confirmed']:
        record['stage'] = 'REPLACE'
        return [dict(event='REPLACE_ENCHANT', args=[target['gear']['enchantments'][0]['name'], definition['name']])]
    result = host._shared_direct_trade_command_locked(request, snapshot, _cursor=True)
    host._clear_item_targeting_locked()
    return result


def cursor_view(host, value):
    record = host._item_target
    if not isinstance(record, dict) or 'shared_trade_request' not in record:
        return
    target = value.get('item_targeting')
    if isinstance(target, dict) and target.get('active'):
        target['shared_trade'] = True
        for key in _modules()[1].CONTEXT:
            target['shared_trade_' + key] = copy.deepcopy(record['shared_trade_request']['shared_trade_' + key])
