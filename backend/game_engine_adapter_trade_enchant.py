"""Non-transferred trade slot seven uses the existing gear/enchantment contracts."""
import copy
from backend import game_engine_enchants as enchants, game_engine_gear as gear

def select_item(host,offer,instance_id):
    item=host._item_instance_locked(instance_id)
    if (not item or item.get('owner_id')!='player' or item.get('location') not in ('INVENTORY','EQUIPPED')
            or not isinstance(item.get('gear'),dict)):raise ValueError('TRADE_ENCHANT_OWNED_GEAR_REQUIRED')
    if host._item_binding_locked(item):raise ValueError('ITEM_PENDING_CONFIRMATION')
    if item['instance_id'] in offer['slots'].values():raise ValueError('TRADE_ITEM_ALREADY_OFFERED')
    offer['enchant_item']=item['instance_id'];offer['target_items']=[];offer['enchant_id']=''

def select_enchant(host,offer,enchant_id):
    item=host._item_instance_locked(offer.get('enchant_item'))
    definition=enchants.definition(enchant_id)
    if not item or not definition:raise ValueError('TRADE_ENCHANT_TARGET_AND_RECIPE_REQUIRED')
    if host._progression.get('level',1)<definition['required_level']:raise ValueError('ENCHANT_LEVEL_REQUIRED')
    scroll=next((i for i in host._item_instances.values() if i.get('owner_id')=='player' and i.get('location')=='INVENTORY'
        and i.get('scroll_enchant_id')==definition['id']),None)
    if not scroll:raise ValueError('ENCHANT_SCROLL_REQUIRED')
    if host._item_binding_locked(item) or host._item_binding_locked(scroll):raise ValueError('ITEM_PENDING_CONFIRMATION')
    table=dict(host._gear_tables,enchantments=dict(host._gear_tables['enchantments'],**{definition['id']:definition}))
    ok,result=gear.apply_enchant(copy.deepcopy(item['gear']),definition['id'],table)
    if not ok:raise ValueError(result['error'])
    offer.update(enchant_id=definition['id'],enchant_scroll=scroll['instance_id'])

def apply(host,offer):
    if not offer.get('enchant_item'):return
    item=host._item_instance_locked(offer['enchant_item']);definition=enchants.definition(offer.get('enchant_id',''))
    if not definition or not item or item.get('owner_id')!='player' or item.get('location') not in ('INVENTORY','EQUIPPED'):
        raise ValueError('TRADE_ENCHANT_OFFER_CHANGED')
    if host._progression.get('level',1)<definition['required_level']:raise ValueError('ENCHANT_LEVEL_REQUIRED')
    scroll=host._item_instance_locked(offer.get('enchant_scroll'))
    if (not scroll or scroll.get('scroll_enchant_id')!=definition['id'] or scroll.get('owner_id')!='player'
            or scroll.get('location')!='INVENTORY'):raise ValueError('TRADE_ENCHANT_SCROLL_CHANGED')
    if host._item_binding_locked(item) or host._item_binding_locked(scroll):raise ValueError('ITEM_PENDING_CONFIRMATION')
    table=dict(host._gear_tables,enchantments=dict(host._gear_tables['enchantments'],**{definition['id']:definition}))
    working=copy.deepcopy(item['gear']);ok,result=gear.apply_enchant(working,definition['id'],table)
    if not ok:raise ValueError(result['error'])
    if not host._consume_inventory_item_locked(scroll):raise ValueError('ENCHANT_SCROLL_CONSUME_FAILED')
    item['gear']=working
