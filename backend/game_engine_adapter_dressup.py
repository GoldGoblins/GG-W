"""An ephemeral dressing-room look using the shared GG character and items."""
import copy
import math
from backend import game_engine_items as items
from backend.game_engine_adapter_item_info import INV

HELD=('MAIN_HAND','OFF_HAND','RANGED')
VISIBLE={'HEAD','SHOULDERS','SHIRT','CHEST','WAIST','LEGS','FEET','WRISTS','HANDS','BACK','TABARD',*HELD}


def inventory_type(definition):
    family=definition.get('weapon_subtype',definition.get('firearm_id','').split('.')[-1])
    if not family:family=str(definition.get('definition_id',definition.get('id',''))).removeprefix('item.weapon_')
    if family=='shield':return 14
    if family=='bow':return 15
    if family in ('pistol','rifle','shotgun','crossbow','wand'):return 26
    if family=='thrown':return 25
    if definition.get('wielding',definition.get('wielding_reference'))=='2H':return 17
    return INV.get(definition.get('equip_slot',definition.get('equipped_slot')),0)


def held_lanes(rows,order,catalog):
    """Original 0x504bc0 held eviction, evaluated only in the preview clone."""
    lanes={}
    for slot in ('MAIN_HAND','OFF_HAND'):
        if slot in rows and slot not in order:lanes[slot]=rows[slot]
    def kind(row):return inventory_type(dict(items.definition(catalog,row['definition_id']) or {},**row))
    for slot in order:
        row=rows.get(slot)
        if not row:continue
        off=slot=='OFF_HAND' or slot=='RANGED' and kind(row)==15
        mine,other=('OFF_HAND','MAIN_HAND') if off else ('MAIN_HAND','OFF_HAND')
        if other in lanes:
            m,o=(kind(lanes[other]),kind(row)) if off else (kind(row),kind(lanes[other]))
            if m not in (13,21) or o not in (13,14,22,23):lanes.pop(other)
        lanes[mine]=row
    for slot in HELD:rows.pop(slot,None)
    for lane,row in lanes.items():
        result=copy.deepcopy(row)
        result['equipped_slot']='RANGED' if kind(row) in (15,25,26) else lane
        rows[result['equipped_slot']]=result


class DressupMixin:
    def _clear_dressup_locked(self):
        self._dressup=dict(open=False,bare=False,substitutions={},held_order=[],angle=0.)

    def _dressup_command_locked(self,row):
        op=row['op']
        if op=='DressupClose':self._clear_dressup_locked();return []
        if op=='DressupDress':
            angle=self._dressup['angle'];self._clear_dressup_locked();self._dressup.update(open=True,angle=angle)
            return []
        if op=='DressupUndress':
            self._dressup.update(open=True,bare=True)
            self._dressup['substitutions']={key:value for key,value in self._dressup['substitutions'].items() if key in HELD}
            return []
        if op=='DressupRotate':
            angle=row.get('angle')
            if isinstance(angle,bool) or not isinstance(angle,(int,float)) or not math.isfinite(angle) or abs(angle)>360000:
                raise ValueError('DRESSUP_ANGLE_INVALID')
            if not self._dressup['open']:raise ValueError('DRESSUP_CLOSED')
            self._dressup['angle']=angle%360.;return []
        if op!='DressupTryOn':raise ValueError('DRESSUP_COMMAND_UNKNOWN')
        template=next((t for t in self._item_templates_view_locked() if t['item_id']==row.get('id')),None)
        if not template:raise ValueError('DRESSUP_TEMPLATE_UNKNOWN')
        ref=template['definition_id'];definition=items.definition(self._item_catalog,ref) or {}
        slot=definition.get('equip_slot')
        if inventory_type(definition) in (15,25,26):slot='RANGED'
        self._dressup['open']=True
        if slot not in VISIBLE:return []
        self._dressup['substitutions'][slot]=ref
        if slot in HELD:
            self._dressup['held_order']=[key for key in self._dressup['held_order'] if key!=slot]+[slot]
        return []

    def _dressup_view_locked(self):
        state=self._dressup
        if not state['open']:return dict(open=False,equipment=[],angle=0.)
        rows={item['equipped_slot']:self._service_item_view_locked(item['instance_id']) for item in self._player_equipped_instances_locked()
              if item['equipped_slot'] in VISIBLE and (not state['bare'] or item['equipped_slot'] in HELD)
              and (item['equipped_slot']!='HEAD' or self._player_display['helm'])
              and (item['equipped_slot']!='BACK' or self._player_display['cloak'])}
        for slot,ref in state['substitutions'].items():
            # This is only a render descriptor; it never enters the canonical
            # registry, inventory counts, trade or character save.
            source=items.make_instance(self._item_catalog,'dressup-'+str(next(t['item_id'] for t in self._item_templates_view_locked() if t['definition_id']==ref)),
                                       ref,location='EQUIPPED',owner_id='preview',equipped_slot=slot)
            if ref=='item.guild_tabard':
                cloth=next((r for r in self._item_instances.values() if r['definition_id']==ref and r.get('owner_id')=='player'),None)
                if cloth:source=copy.deepcopy(cloth);source['equipped_slot']=slot;source['location']='EQUIPPED'
            view=items.instance_view(self._item_catalog,source,sim_time=self._sim_time);view['preview_only']=True;rows[slot]=view
        held_lanes(rows,state['held_order'],self._item_catalog)
        return dict(open=True,bare=state['bare'],angle=state['angle'],equipment=list(rows.values()))
