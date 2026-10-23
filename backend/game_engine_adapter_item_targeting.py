"""Original item-target cursor and confirmations over real GG enchant scrolls."""
import copy
from backend import game_engine_enchants as enchants, game_engine_gear as gear


class ItemTargetingMixin:
    def _clear_item_targeting_locked(self):
        self._item_target_generation=getattr(self,'_item_target_generation',0)+1
        self._item_target=None

    def _item_targeting_locked(self,item):
        record=getattr(self,'_item_target',None)
        return bool(record and isinstance(item,dict) and record['expires']>self._service_now_locked()
                    and item.get('instance_id') in (record['scroll'],record.get('target')))

    def _enchant_source_locked(self):
        record=self._item_target
        scroll=self._item_instance_locked(record['scroll']) if record else None
        if (not record or not scroll or scroll.get('owner_id')!='player' or scroll.get('location')!='INVENTORY'
                or scroll.get('slot_index')!=record['source_slot'] or scroll.get('scroll_enchant_id')!=record['enchant']
                or record['expires']<=self._service_now_locked()):raise ValueError('ENCHANT_SOURCE_CHANGED')
        definition=enchants.definition(record['enchant'])
        if not definition:raise ValueError('ENCHANT_RECIPE_UNKNOWN')
        if self._progression.get('level',1)<definition['required_level']:raise ValueError('ENCHANT_LEVEL_REQUIRED')
        return record,scroll,definition

    def _enchant_item_locked(self,identity):
        item=self._item_instance_locked(identity)
        if (not item or item.get('owner_id')!='player' or item.get('location') not in ('INVENTORY','EQUIPPED')
                or not isinstance(item.get('gear'),dict)):raise ValueError('ENCHANT_OWNED_GEAR_REQUIRED')
        if item.get('bound_to') and item['bound_to']!=str(self._persistence_key):raise ValueError('ENCHANT_OWNER_CHANGED')
        return item

    def _enchant_checked_gear_locked(self,item,definition,replace):
        working=copy.deepcopy(item['gear'])
        if replace and working.get('enchantments'):working['enchantments'].pop(0)
        table=dict(self._gear_tables,enchantments=dict(self._gear_tables['enchantments'],**{definition['id']:definition}))
        ok,result=gear.apply_enchant(working,definition['id'],table)
        if not ok:raise ValueError(result['error'])
        # The original cursor replaces the permanent slot. GG's other authored
        # enchant slots remain intact; the new permanent row occupies slot zero.
        working['enchantments'].insert(0,working['enchantments'].pop())
        return working

    def _enchant_prepare_locked(self,record,item,definition):
        old=(item['gear'].get('enchantments') or [None])[0]
        self._enchant_checked_gear_locked(item,definition,old is not None)
        if definition.get('binds') is True and not item.get('bound_to') and not record.get('bind_confirmed'):
            record['stage']='BIND'
            return [dict(event='BIND_ENCHANT',args=[])]
        if old and not record.get('replace_confirmed'):
            record['stage']='REPLACE'
            return [dict(event='REPLACE_ENCHANT',args=[str(old.get('name','Enchantment')),definition['name']])]
        working=self._enchant_checked_gear_locked(item,definition,old is not None)
        _,scroll,_=self._enchant_source_locked()
        self._item_target=None
        if not self._consume_inventory_item_locked(scroll):raise ValueError('ENCHANT_SCROLL_CONSUME_FAILED')
        item['gear']=working
        if definition.get('binds') is True:item['bound_to']=str(self._persistence_key)
        return [dict(event='BAG_UPDATE',args=[0]),dict(event='UNIT_INVENTORY_CHANGED',args=['player'])]

    def _enchant_cursor_command_locked(self,row):
        op=row['op']
        if op=='EnchantOpen':
            scroll=self._item_instance_locked(row.get('item'))
            if not scroll or scroll.get('location')!='INVENTORY' or scroll.get('owner_id')!='player':raise ValueError('ENCHANT_SCROLL_REQUIRED')
            definition=enchants.definition(scroll.get('scroll_enchant_id',''))
            if not definition:raise ValueError('ENCHANT_SCROLL_REQUIRED')
            if self._progression.get('level',1)<definition['required_level']:raise ValueError('ENCHANT_LEVEL_REQUIRED')
            if self._item_binding_locked(scroll):raise ValueError('ITEM_PENDING_CONFIRMATION')
            self._ensure_inventory_slots_locked();self._clear_wrapping_locked();self._clear_item_targeting_locked()
            self._item_target=dict(scroll=scroll['instance_id'],source_slot=scroll['slot_index'],enchant=definition['id'],
                                  expires=self._service_now_locked()+120.,stage='SELECT')
            return []
        if row.get('target_generation')!=self._item_target_generation:raise ValueError('ENCHANT_CURSOR_CHANGED')
        if op=='EnchantCancel':self._clear_item_targeting_locked();return []
        record,scroll,definition=self._enchant_source_locked()
        if op=='EnchantPick':
            item=self._enchant_item_locked(row.get('item'))
            if self._item_binding_locked(item) and item['instance_id']!=record.get('target'):raise ValueError('ITEM_PENDING_CONFIRMATION')
            self._item_target_generation+=1
            record.update(target=item['instance_id'],target_state=copy.deepcopy(item),bind_confirmed=False,replace_confirmed=False)
            return self._enchant_prepare_locked(record,item,definition)
        item=self._enchant_item_locked(record.get('target'))
        if item!=record.get('target_state'):
            raise ValueError('ENCHANT_TARGET_CHANGED')
        if op=='EnchantBindConfirm' and record['stage']=='BIND':record['bind_confirmed']=True
        elif op=='EnchantReplaceConfirm' and record['stage']=='REPLACE':record['replace_confirmed']=True
        else:raise ValueError('ENCHANT_CONFIRMATION_CHANGED')
        return self._enchant_prepare_locked(record,item,definition)

    def _item_targeting_view_locked(self):
        record=self._item_target
        if record:
            try:self._enchant_source_locked()
            except ValueError:self._clear_item_targeting_locked();record=None
        if not record:return dict(active=False,generation=self._item_target_generation,locked_items=[])
        item=self._item_instance_locked(record.get('target')) or {}
        definition=enchants.definition(record['enchant'])
        return dict(active=True,generation=self._item_target_generation,stage=record['stage'],scroll=record['scroll'],
                    target=record.get('target'),name=item.get('name',''),enchant_name=definition['name'],
                    locked_items=[record['scroll']]+([record['target']] if record.get('target') else []))
