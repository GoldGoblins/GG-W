"""Paid physical guild charters and finite consent in the existing local world."""
import copy
import math
from backend import game_engine_items as items
from backend.game_engine_adapter_local_client import text
from backend.game_engine_adapter_social import event, guild_record

CHARTER_COST = 10000
SIGNATURES = 3  # GG's initial island has seven named inhabitants, not a remote realm.
REGISTRAR = 'npc-wanderer-01'


class PetitionsMixin:
    def _restore_petitions_locked(self):
        offer=self._services.setdefault('petition_offer',None)
        if offer is not None:
            if (not isinstance(offer,dict) or set(offer)!= {'item','target','ready','expires'}
                    or not isinstance(offer['item'],str) or len(offer['item'])>96
                    or not isinstance(offer['target'],str) or len(offer['target'])>64
                    or any(type(offer[k]) not in (int,float) or not math.isfinite(offer[k]) for k in ('ready','expires'))
                    or not offer['ready']<=offer['expires']<=offer['ready']+30):
                raise ValueError('PETITION_OFFER_SAVE_INVALID')

    def _petition_item_locked(self,key,owner=None):
        item=self._item_instance_locked(key)
        if (not item or item.get('definition_id')!='item.guild_charter'
                or item.get('location') not in ('INVENTORY','POCKET') or not isinstance(item.get('petition'),dict)):
            raise ValueError('PETITION_ITEM_CHANGED_OR_MISSING')
        record=item['petition'];signers=record.get('signers')
        if (record.get('owner')!=item.get('owner_id') or (owner is not None and record['owner']!=owner)
                or record.get('max_signatures')!=SIGNATURES or not isinstance(signers,list)
                or len(signers)>SIGNATURES or len(set(signers))!=len(signers) or record['owner'] in signers):
            raise ValueError('PETITION_RECORD_INVALID')
        if owner=='player' and item.get('location')!='INVENTORY':raise ValueError('PETITION_NOT_IN_BACKPACK')
        return item

    def _owned_charters_locked(self,owner='player'):
        rows=[]
        for item in self._item_instances.values():
            if item.get('definition_id')=='item.guild_charter' and item.get('owner_id')==owner:
                try:rows.append(self._petition_item_locked(item['instance_id'],owner))
                except ValueError:continue
        return rows

    def _petition_create_locked(self,owner,name):
        if self._owned_charters_locked(owner):raise ValueError('PETITION_ALREADY_OWNED')
        name=text(name,48)
        if name!=name.strip() or '  ' in name or any(ord(c)<32 for c in name):raise ValueError('GUILD_NAME_INVALID')
        if len(self._item_instances)>=items.MAX_WORLD_INSTANCES:raise ValueError('ITEM_INSTANCE_CAPACITY')
        if owner=='player':self._ensure_inventory_slots_locked()
        self._service_money_locked(owner,-CHARTER_COST)
        self._service_money_locked(REGISTRAR,CHARTER_COST)
        key='charter-'+str(self._service_id_locked())
        item=items.make_instance(self._item_catalog,key,'item.guild_charter',location='MAIL',owner_id=owner)
        item['petition']=dict(title=name,owner=owner,max_signatures=SIGNATURES,signers=[])
        self._item_instances[key]=item
        self._service_move_locked(item,'INVENTORY' if owner=='player' else 'POCKET',owner)
        if owner!='player' and not self._npc_add_inventory_ref_locked(self._individual_state['individuals'][owner],'item.guild_charter'):
            raise ValueError('NPC_INVENTORY_FULL')
        return item

    def _petition_focus_locked(self,row,owner=None):
        self._service_session_locked(row,'petition')
        item=self._petition_item_locked(self._service_windows['petition'],owner)
        if item['owner_id']!='player':self._service_person_locked(item['owner_id'],nearby=True)
        return item

    def _petition_command_locked(self,row):
        op=row['op']
        if op=='PetitionRegistrarOpen':
            target=self._service_person_locked(row.get('target','target'),nearby=True)
            if target!=REGISTRAR:raise ValueError('GUILD_REGISTRAR_REQUIRED')
            self._service_generation+=1;self._service_windows['registrar']=True
            return event('GUILD_REGISTRAR_SHOW')
        if op=='PetitionNameRefused':raise ValueError('GUILD_NAME_INVALID')
        if op in ('PetitionRegistrarClose','PetitionClose'):
            if row.get('session')!=self._service_generation:raise ValueError('SERVICE_WINDOW_CHANGED_OR_CLOSED')
            self._service_windows['registrar' if op=='PetitionRegistrarClose' else 'petition']=False if op=='PetitionRegistrarClose' else None
            return event('GUILD_REGISTRAR_CLOSED' if op=='PetitionRegistrarClose' else 'PETITION_CLOSED')
        if op=='PetitionBuy':
            self._service_session_locked(row,'registrar');self._service_person_locked(REGISTRAR,nearby=True)
            if self._services['guild']:raise ValueError('GUILD_ALREADY_MEMBER')
            self._petition_create_locked('player',row.get('name'))
            return event('BAG_UPDATE',0)
        if op=='PetitionOpen':
            item=self._petition_item_locked(row.get('item'),'player')
            self._service_generation+=1;self._service_windows['petition']=item['instance_id']
            return event('PETITION_SHOW')
        if op=='PetitionRequestOffer':
            if self._services['guild']:raise ValueError('GUILD_ALREADY_MEMBER')
            target=self._service_person_locked(row.get('target'),nearby=True)
            if target=='player':raise ValueError('PETITION_OTHER_OWNER_REQUIRED')
            charters=self._owned_charters_locked(target)
            item=charters[0] if charters else self._petition_create_locked(target,row.get('name'))
            self._service_generation+=1;self._service_windows['petition']=item['instance_id']
            return event('PETITION_SHOW')
        if op=='PetitionTurnIn':
            self._service_session_locked(row,'registrar')
            self._service_person_locked(REGISTRAR,nearby=True)
            if self._services['guild']:raise ValueError('GUILD_ALREADY_MEMBER')
            charters=self._owned_charters_locked()
            if not charters:raise ValueError('PETITION_NOT_IN_BACKPACK')
            item=charters[0];record=item['petition']
            if len(record['signers'])!=SIGNATURES:raise ValueError('PETITION_NEEDS_SIGNATURES')
            valid={p['id'] for p in self._local_people_locked()}
            if any(p not in valid for p in record['signers']):raise ValueError('PETITION_SIGNER_UNAVAILABLE')
            self._services['guild']=guild_record(record['title'],members=record['signers'])
            if not self._consume_inventory_item_locked(item):raise ValueError('PETITION_ITEM_CHANGED_OR_MISSING')
            self._services['petition_offer']=None;self._service_windows['petition']=None
            return event('PLAYER_GUILD_UPDATE','player')+event('GUILD_ROSTER_UPDATE')+event('PETITION_CLOSED')+event('BAG_UPDATE',0)
        item=self._petition_focus_locked(row,'player' if op in ('PetitionRename','PetitionOffer') else None)
        record=item['petition']
        if op=='PetitionRename':
            name=text(row.get('name'),48)
            if name!=name.strip() or '  ' in name or any(ord(c)<32 for c in name):raise ValueError('GUILD_NAME_INVALID')
            if name==record['title']:return []
            # Existing signers agreed to the old name; renaming requires new consent.
            record.update(title=name,signers=[]);self._services['petition_offer']=None
            return event('PETITION_UPDATE')
        if op=='PetitionSign':
            if self._services['guild'] or record['owner']=='player':raise ValueError('PETITION_CANNOT_SIGN')
            if 'player' in record['signers'] or len(record['signers'])>=SIGNATURES:raise ValueError('PETITION_ALREADY_SIGNED_OR_FULL')
            record['signers'].append('player')
            return event('PETITION_UPDATE')
        if op=='PetitionOffer':
            if self._services['guild']:raise ValueError('GUILD_ALREADY_MEMBER')
            if self._services['petition_offer']:raise ValueError('PETITION_OFFER_PENDING')
            target=self._service_person_locked(row.get('target','target'),nearby=True)
            person=self._individual_state['individuals'].get(target,{})
            if target=='player' or person.get('role')=='CRITTER':raise ValueError('PETITION_SIGNER_REQUIRED')
            if target in record['signers'] or len(record['signers'])>=SIGNATURES:raise ValueError('PETITION_ALREADY_SIGNED_OR_FULL')
            now=self._service_now_locked()
            self._services['petition_offer']=dict(item=item['instance_id'],target=target,ready=now+2.,expires=now+15.)
            return event('PETITION_UPDATE')
        raise ValueError('PETITION_COMMAND_UNKNOWN')

    def _settle_petitions_locked(self,now):
        offer=self._services.get('petition_offer')
        if not offer or now<offer['ready']:return
        self._services['petition_offer']=None;self._services['revision']+=1
        if now>offer['expires'] or self._services['guild']:return
        try:
            item=self._petition_item_locked(offer['item'],'player')
            target=self._service_person_locked(offer['target'],nearby=True)
            if self._combat_state['actors'].get(target,{}).get('engaged_target'):return
            if target not in item['petition']['signers'] and len(item['petition']['signers'])<SIGNATURES:
                item['petition']['signers'].append(target)
        except ValueError:return

    def _petition_view_locked(self):
        item=None;key=self._service_windows.get('petition')
        if key:
            try:item=self._petition_item_locked(key)
            except ValueError:self._service_windows['petition']=None
        record=None
        if item:
            record=copy.deepcopy(item['petition']);record.update(item=item['instance_id'],is_originator=record['owner']=='player',
                owner_name=self._service_unit_locked(record['owner'])['name'],
                signer_names=[self._service_unit_locked(p)['name'] for p in record['signers']])
        return dict(open=record is not None,registrar_open=bool(self._service_windows.get('registrar')),cost=CHARTER_COST,
            record=record,can_sign=bool(record and not record['is_originator'] and not self._services['guild']
                and 'player' not in record['signers'] and len(record['signers'])<SIGNATURES),
            owned=[dict(item=i['instance_id'],title=i['petition']['title']) for i in self._owned_charters_locked()],
            offer=copy.deepcopy(self._services.get('petition_offer')))
