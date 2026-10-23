"""Soulbind decisions refer to exact items in the canonical character registry."""
from backend import game_engine_items as items


def bonding(definition):
    value=(definition or {}).get('bonding',0)
    return value if type(value) is int and 0<=value<=5 else 0


class ItemBindingMixin:
    def _bind_acquired_item_locked(self,item):
        if (self._item_owned_state(item.get('location'),item.get('owner_id'))
                and not item.get('bound_to')
                and bonding(items.definition(self._item_catalog,item.get('definition_id'))) in (1,4)):
            item['bound_to']=str(self._persistence_key)

    def _clear_item_binding_locked(self):
        self._item_binding_generation=getattr(self,'_item_binding_generation',0)+1
        self._item_pending_equips={};self._item_pending_use=None

    def _item_binding_needed_locked(self,item,mode):
        return not item.get('bound_to') and bonding(items.definition(self._item_catalog,item['definition_id']))==(2 if mode=='EQUIP' else 3)

    def _item_binding_locked(self,item):
        if not isinstance(item,dict) or not item.get('instance_id'):return False
        if self._wrapping_locked(item):return True
        if self._item_targeting_locked(item):return True
        identity=item['instance_id']
        records=list(getattr(self,'_item_pending_equips',{}).values())
        pending=getattr(self,'_item_pending_use',None)
        if pending:records.append(pending)
        if not records:return False
        now=self._service_now_locked()
        return any(r['expires']>now and (r['item']==identity or identity in r.get('worn',{}).values()) for r in records)

    def _item_binding_request_locked(self,op,item,slot='',popup='EQUIP_BIND_CONFIRM'):
        try:events=self._service_command_locked(dict(op=op,item=item['instance_id'],slot=slot,popup=popup))
        except ValueError as error:return self._local_action_error_locked(str(error))
        value=self.snapshot_locked();value['client_events']=events;return value

    def _item_binding_source_locked(self,record):
        item=self._item_instance_locked(record['item'])
        if (not item or item.get('owner_id')!='player' or item.get('location')!='INVENTORY'
                or item.get('definition_id')!=record['definition'] or item.get('slot_index')!=record['source_slot']
                or item.get('bound_to') or record['expires']<=self._service_now_locked()):
            raise ValueError('ITEM_BIND_SOURCE_CHANGED')
        return item

    def _item_binding_command_locked(self,row):
        op=row['op']
        if op in ('ItemBindingEquip','ItemBindingUse'):
            item=self._item_instance_locked(row.get('item'))
            mode='EQUIP' if op=='ItemBindingEquip' else 'USE'
            if (not item or item.get('owner_id')!='player' or item.get('location')!='INVENTORY'
                    or not self._item_binding_needed_locked(item,mode)):
                raise ValueError('ITEM_BIND_SOURCE_CHANGED')
            self._item_binding_generation+=1
            record=dict(item=item['instance_id'],definition=item['definition_id'],source_slot=item['slot_index'],
                expires=self._service_now_locked()+120.,generation=self._item_binding_generation)
            if mode=='USE':
                if self._item_binding_locked(item):raise ValueError('ITEM_PENDING_CONFIRMATION')
                self._item_pending_equips={};self._item_pending_use=record
                return [dict(event='USE_BIND_CONFIRM',args=[])]
            if self._item_binding_locked(item):raise ValueError('ITEM_PENDING_CONFIRMATION')
            slot=row.get('slot','')
            allowed=items.allowed_equip_slots(self._item_catalog,item['definition_id'],item['instance_id'])
            if slot not in allowed:raise ValueError('ITEM_EQUIP_SLOT_INCOMPATIBLE')
            slots=[slot]+(['OFF_HAND'] if slot=='MAIN_HAND' and items.equipment_wielding(item)=='2H' else [])
            worn={i['equipped_slot']:i['instance_id'] for i in self._player_equipped_instances_locked()}
            record.update(slot=slot,kind=row.get('popup','EQUIP_BIND_CONFIRM'),worn={key:worn.get(key,'') for key in slots})
            available=next((n for n in range(64) if n not in self._item_pending_equips),None)
            if available is None:raise ValueError('ITEM_BIND_CONFIRMATION_CAPACITY')
            self._item_pending_equips={available:record};self._item_pending_use=None
            return [dict(event=record['kind'],args=[available])]
        if row.get('binding_generation')!=self._item_binding_generation:raise ValueError('ITEM_BIND_WINDOW_CHANGED')
        if op=='ItemBindingEquipAnswer':
            index=row.get('index')
            if type(index) is not int or not 0<=index<64:raise ValueError('ITEM_BIND_INDEX_INVALID')
            record=self._item_pending_equips.get(index)
            if not record:return []
            if type(row.get('accept')) is not bool:raise ValueError('ITEM_BIND_VERDICT_INVALID')
            if not row['accept']:self._item_pending_equips.pop(index);return []
            item=self._item_binding_source_locked(record)
            worn={i['equipped_slot']:i['instance_id'] for i in self._player_equipped_instances_locked()}
            worn={key:worn.get(key,'') for key in record['worn']}
            if worn!=record['worn']:raise ValueError('ITEM_BIND_DESTINATION_CHANGED')
            self._item_pending_equips.pop(index)
            value=self.equip_item(item['instance_id'],record['slot'],_bind_confirmed=True)
        elif op=='ItemBindingUseConfirm':
            record=self._item_pending_use
            if not record:return []
            item=self._item_binding_source_locked(record);self._item_pending_use=None
            value=self.action_use_item(item['definition_id'],item['instance_id'],_bind_confirmed=True)
        elif op=='ItemBindingUseCancel':
            self._item_pending_use=None;return []
        else:raise ValueError('ITEM_BIND_COMMAND_UNKNOWN')
        if value.get('error'):raise ValueError(value['error'])
        if item['instance_id'] in self._item_instances:item['bound_to']=str(self._persistence_key)
        return [dict(event='BAG_UPDATE',args=[0]),dict(event='UNIT_INVENTORY_CHANGED',args=['player'])]

    def _item_binding_view_locked(self):
        now=self._service_now_locked()
        self._item_pending_equips={k:r for k,r in self._item_pending_equips.items() if r['expires']>now}
        if self._item_pending_use and self._item_pending_use['expires']<=now:self._item_pending_use=None
        def view(record,index=None):
            if not record:return None
            item=self._item_instance_locked(record['item']) or {}
            return dict(index=index,name=item.get('name','Item'),kind=record.get('kind','USE_BIND_CONFIRM'))
        return dict(generation=self._item_binding_generation,
            locked_items=sorted({identity for r in list(self._item_pending_equips.values())+([self._item_pending_use] if self._item_pending_use else [])
                for identity in [r['item'],*r.get('worn',{}).values()] if identity}),
            equips=[view(r,n) for n,r in self._item_pending_equips.items()],use=view(self._item_pending_use))
