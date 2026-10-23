"""Wrapping consumes paper and changes one exact owned item's saved payload."""
import copy
from backend import game_engine_items as items

PAPER='item.gg_wrapping_paper'
GIFT='item.gg_wrapped_gift'


class WrappingMixin:
    def _clear_wrapping_locked(self):
        self._gift_wrap_generation=getattr(self,'_gift_wrap_generation',0)+1
        self._gift_wrap=None

    def _wrapping_locked(self,item):
        record=getattr(self,'_gift_wrap',None)
        return bool(record and isinstance(item,dict) and record['item']==item.get('instance_id')
                    and record['expires']>self._service_now_locked())

    def _wrapping_command_locked(self,row):
        op=row['op']
        if op=='InventoryWrapCancel':
            if row.get('wrap_generation')!=self._gift_wrap_generation:raise ValueError('WRAPPING_PAPER_CHANGED')
            self._clear_wrapping_locked();return []
        item=self._item_instance_locked(row.get('item'))
        if not item or item.get('owner_id')!='player' or item.get('location')!='INVENTORY':
            raise ValueError('INVENTORY_OWNED_ITEM_REQUIRED')
        if op=='InventoryWrapOpen':
            definition=items.definition(self._item_catalog,item['definition_id']) or {}
            if 'GIFT_WRAPPER' not in definition.get('tags',[]):raise ValueError('WRAPPING_PAPER_REQUIRED')
            if self._item_binding_locked(item):raise ValueError('ITEM_PENDING_CONFIRMATION')
            self._ensure_inventory_slots_locked();self._gift_wrap_generation+=1
            self._clear_item_targeting_locked()
            self._gift_wrap=dict(item=item['instance_id'],slot=item['slot_index'],expires=self._service_now_locked()+120.)
            return []
        if op=='InventoryUnwrap':
            if item.get('gift_invalid'):raise ValueError('WRAPPED_GIFT_INVALID')
            if item['definition_id']!=GIFT or not isinstance(item.get('gift'),dict):raise ValueError('WRAPPED_GIFT_REQUIRED')
            original=copy.deepcopy(item['gift']['original'])
            original=items.normalize_instance(self._item_catalog,original)
            if not original or original.get('definition_id') in (PAPER,GIFT):raise ValueError('WRAPPED_GIFT_INVALID')
            definition=items.definition(self._item_catalog,original['definition_id'])
            if definition is None:raise ValueError('WRAPPED_GIFT_CONTENT_UNAVAILABLE')
            if (original.get('bound_to') or original.get('kind') in ('QUEST','CONTAINER')
                    or int(original.get('quantity',1))!=1 or int(definition.get('stack_limit',1))!=1
                    or set(definition.get('tags',[]))&{'NO_TRADE','QUEST','SOULBOUND','BOUND','GIFT_WRAPPER'}):
                raise ValueError('WRAPPED_GIFT_INVALID')
            original.update(instance_id=item['instance_id'],owner_id=item['owner_id'],location=item['location'],slot_index=item['slot_index'],container_id='',equipped_slot='')
            self._inventory[GIFT]-=1
            if not self._inventory[GIFT]:self._inventory.pop(GIFT)
            self._inventory[original['definition_id']]=self._inventory.get(original['definition_id'],0)+1
            item.clear();item.update(original)
            return [dict(event='BAG_UPDATE',args=[0])]
        if op!='InventoryWrap':raise ValueError('WRAPPING_COMMAND_UNKNOWN')
        record=self._gift_wrap;paper=self._item_instance_locked(row.get('paper'))
        if (not record or row.get('wrap_generation')!=self._gift_wrap_generation or not paper
                or paper['instance_id']!=record['item'] or paper.get('owner_id')!='player'
                or paper.get('location')!='INVENTORY' or paper.get('slot_index')!=record['slot']
                or record['expires']<=self._service_now_locked()):raise ValueError('WRAPPING_PAPER_CHANGED')
        if 'GIFT_WRAPPER' not in (items.definition(self._item_catalog,paper['definition_id']) or {}).get('tags',[]):raise ValueError('WRAPPING_PAPER_CHANGED')
        definition=items.definition(self._item_catalog,item['definition_id']) or {}
        if item is paper:raise ValueError('WRAPPING_PAPER_CANNOT_WRAP_ITSELF')
        if item.get('bound_to'):raise ValueError('WRAPPING_BOUND_ITEM')
        if item.get('kind') in ('QUEST','CONTAINER') or item.get('definition_id')==GIFT:
            raise ValueError('WRAPPING_ITEM_INELIGIBLE')
        if int(item.get('quantity',1))!=1 or int(definition.get('stack_limit',1))!=1:
            raise ValueError('WRAPPING_STACKABLE_ITEM')
        if definition.get('tags') and set(definition['tags'])&{'NO_TRADE','QUEST','SOULBOUND','BOUND','GIFT_WRAPPER'}:
            raise ValueError('WRAPPING_ITEM_INELIGIBLE')
        if self._item_binding_locked(item):raise ValueError('ITEM_PENDING_CONFIRMATION')
        original=copy.deepcopy(item);self._gift_wrap=None
        if not self._consume_inventory_item_locked(paper):raise ValueError('WRAPPING_PAPER_CONSUME_FAILED')
        self._inventory[item['definition_id']]-=1
        if not self._inventory[item['definition_id']]:self._inventory.pop(item['definition_id'])
        self._inventory[GIFT]=self._inventory.get(GIFT,0)+1
        gift=items.make_instance(self._item_catalog,item['instance_id'],GIFT,owner_id=item['owner_id'],location=item['location'])
        gift.update(slot_index=item['slot_index'],gift=dict(original=original,sender=str(getattr(self,'_local_character_name','Gold Goblin'))[:48]))
        item.clear();item.update(gift)
        return [dict(event='BAG_UPDATE',args=[0])]

    def _wrapping_view_locked(self):
        record=self._gift_wrap
        if record:
            item=self._item_instance_locked(record['item'])
            if (not item or item.get('location')!='INVENTORY' or item.get('owner_id')!='player'
                    or item.get('slot_index')!=record['slot'] or record['expires']<=self._service_now_locked()):
                self._clear_wrapping_locked();record=None
        return dict(wrap=dict(generation=self._gift_wrap_generation,paper=record['item'],source=[0,record['slot']+1]) if record else None)
