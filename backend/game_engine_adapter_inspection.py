"""Live friendly equipment inspection and combat-status projections."""
import math
import time
from backend.game_engine_adapter_gameplay import identity


class InspectionMixin:
    def _inspect_person_locked(self,value):
        person=self._service_person_locked(value)
        if person=='player':return person
        index=self._npc_index_for_id_locked(person)
        friendly=person in self._services['group']['members'] or person in self._services['guild'].get('members',{})
        if not friendly:raise ValueError('INSPECT_FRIENDLY_PERSON_REQUIRED')
        if index is None or not self._alive[index] or math.dist((self._x[0],self._y[0],self._z[0]),(self._x[index],self._y[index],self._z[index]))>10.:raise ValueError('INSPECT_OUT_OF_REACH')
        return person

    def _inspection_command_locked(self,row):
        if row['op']=='InspectClear':self._service_windows['inspection']=None;return []
        person=self._inspect_person_locked(row.get('unit','target'))
        self._service_windows['inspection']=dict(person=person,unit=row.get('unit','target'))
        return [{'event':'UNIT_INVENTORY_CHANGED','args':[row.get('unit','target')]}]

    def _inspection_view_locked(self):
        current=self._service_windows.get('inspection')
        if not current:return dict(open=False)
        try:self._inspect_person_locked(current['person'])
        except ValueError:self._service_windows['inspection']=None;return dict(open=False)
        return dict(open=True,unit=current['unit'],guid=self._service_unit_locked(current['person'])['guid'],
            person=self._service_unit_locked(current['person']),items=[self._service_item_view_locked(r['instance_id']) for r in self._item_instances.values()
                if r.get('owner_id')==current['person'] and r.get('location')=='EQUIPPED'][:19])

    def _auras_view_locked(self):
        rows=[]
        for actor in self._combat_state['actors'].values():
            if actor['id']=='player':guid=1
            elif str(actor['id']).startswith('pet:'):guid=0xfffffff0
            else:
                index=self._npc_index_for_id_locked(actor['id']);guid=index+1 if index is not None else 0
            if not guid:continue
            auras=[]
            for status in actor.get('statuses',[]):
                if status['expires_at']<=self._sim_time:continue
                kind=status['kind'];remaining=max(0.,status['expires_at']-self._sim_time)
                auras.append(dict(id=identity('aura:'+status['source_id']+':'+kind),name=kind.replace('_',' ').title(),
                    description=kind.replace('_',' ').title()+': '+str(status['amount']),icon='Interface\\Icons\\Spell_Nature_'+('Rejuvenation' if kind in ('ward','regen') else 'CorrosiveBreath'),
                    helpful=kind in ('ward','regen'),cancelable=kind in ('ward','regen'),remaining=remaining,duration=remaining,
                    debuff_type='Poison' if kind=='poison' else 'Magic',source=status['source_id'],kind=kind))
            if guid==1:
                sickness=self._services['sickness_until']-max(float(self._services['clock']),time.time())
                if sickness>0:auras.append(dict(id=identity('aura:resurrection-sickness'),name='Resurrection sickness',description='Health, damage and armor reduced by 75%.',
                    icon='Interface\\Icons\\Spell_Shadow_AnimateDead',helpful=False,cancelable=False,remaining=sickness,duration=sickness,debuff_type=None))
            rows.append(dict(guid=guid,auras=auras))
        return rows

    def _aura_command_locked(self,row):
        actor=self._combat_state['actors'].get('player',{});spell=row.get('id')
        status=next((s for s in actor.get('statuses',[]) if identity('aura:'+s['source_id']+':'+s['kind'])==spell and s['expires_at']>self._sim_time),None)
        if not status or status['kind'] not in ('ward','regen'):raise ValueError('AURA_NOT_CANCELABLE')
        actor['statuses'].remove(status)
        return [{'event':'UNIT_AURA','args':['player']}]
