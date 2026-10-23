"""Original bag intents use exact registry instances and one character commit."""
import math
from backend import game_engine_items as items
from backend.game_engine_adapter_local_client import integer


class InventoryServicesMixin:
    def _inventory_service_command_locked(self,row):
        item=self._item_instance_locked(row.get('item'));op=row['op']
        if not item or item.get('owner_id')!='player' or item.get('location') not in ('INVENTORY','EQUIPPED'):raise ValueError('INVENTORY_OWNED_ITEM_REQUIRED')
        if op=='InventoryDropOnUnit':
            target=row.get('target')
            if target=='pet':
                pet=self._active_pet_locked()
                if not pet or math.dist((self._x[0],self._y[0]-.65,self._z[0]),tuple(pet.get(k,0.) for k in ('x','y','z')))>3.75:raise ValueError('PET_NOT_IN_REACH')
                return self._pet_training_command_locked(dict(op='PetFeed',item=item['instance_id']))
            person=self._service_person_locked(target,nearby=True)
            if person=='player':raise ValueError('TRADE_CANNOT_TRADE_SELF')
            self._service_item_locked(item['instance_id'])
            result=[]
            if not self._service_windows['trade'] or self._service_trade.get('target')!=person:
                result+=self._trade_command_locked(dict(op='TradeOpen',target=person))
            if item['instance_id'] in self._service_trade['slots'].values():raise ValueError('TRADE_ITEM_ALREADY_OFFERED')
            slot=next((n for n in range(1,7) if str(n) not in self._service_trade['slots']),None)
            if slot is None:raise ValueError('TRADE_OFFER_FULL')
            return result+self._trade_command_locked(dict(op='TradeSet',session=self._service_generation,slot=slot,item=item['instance_id']))
        if op=='InventoryDestroy':
            if item['location']!='INVENTORY':raise ValueError('INVENTORY_BAG_ITEM_REQUIRED')
            count=integer(row.get('count',0),0,int(item.get('quantity',1))) or int(item.get('quantity',1))
            if not self._consume_inventory_item_locked(item,count):raise ValueError('INVENTORY_ITEM_CHANGED')
        elif op=='InventoryAutoStore':
            count=row.get('count')
            if count is not None:integer(count,1,int(item.get('quantity',1)))
            if item['location']=='EQUIPPED':
                if count is not None:raise ValueError('INVENTORY_EQUIPMENT_CANNOT_SPLIT')
                self._service_move_locked(item,'INVENTORY','player')
            else:
                definition=items.definition(self._item_catalog,item['definition_id']) or {};limit=max(1,int(definition.get('stack_limit',1)))
                candidates=[r for r in self._item_instances.values() if r is not item and r.get('owner_id')=='player' and r.get('location')=='INVENTORY']
                if count is None:
                    # Auto-store a whole stack fills compatible partial stacks;
                    # its remainder already belongs to this same backpack.
                    for other in candidates:
                        if item['instance_id'] not in self._item_instances:break
                        if int(other.get('quantity',1))<limit and self._stacks_compatible(item,other):
                            result=self.transfer_inventory_stack(item['instance_id'],int(other['slot_index']),0)
                            if result.get('error'):raise ValueError(result['error'])
                else:
                    target=next((r['slot_index'] for r in candidates if int(r.get('quantity',1))+count<=limit and self._stacks_compatible(item,r)),None)
                    if target is None:
                        used={r['slot_index'] for r in candidates+[item]};target=next((n for n in range(items.MAX_INVENTORY_SLOTS) if n not in used),None)
                    if target is None:raise ValueError('ITEM_INVENTORY_FULL')
                    result=self.transfer_inventory_stack(item['instance_id'],int(target),count)
                    if result.get('error'):raise ValueError(result['error'])
        else:raise ValueError('INVENTORY_COMMAND_UNKNOWN')
        return [{'event':'BAG_UPDATE','args':[0]}]
