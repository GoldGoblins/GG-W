"""Paid local flight routes, consented summons and delayed stuck recovery.

Routes connect the real authored GG towns. Flight progress shares the saved
character and fixed-step simulation; no server or second actor is created.
"""
import copy
import math
import time
from backend import game_engine_world_places as places

def defaults():return dict(taxi_flight=None,stuck_cast=None,stuck_until=0.)

class TravelMixin:
    def _travel_nodes_locked(self):
        nodes=getattr(self,'_engine_travel_nodes',None)
        if nodes is None:
            nodes=[dict(id=r['id'],name=r['name'],x=float(r['x']),z=float(r['z'])) for r in places.catalog()['places'] if r['kind']=='TOWN']
            if not 2<=len(nodes)<=32:raise ValueError('TAXI_NETWORK_CAPACITY')
            self._engine_travel_nodes=nodes
        return nodes

    def _restore_travel_locked(self):
        for k,v in defaults().items():self._services.setdefault(k,copy.deepcopy(v))
        flight=self._services['taxi_flight'];self._services['stuck_cast']=None
        if flight:
            if not isinstance(flight,dict) or flight['destination'] not in {r['id'] for r in self._travel_nodes_locked()}:raise ValueError('TAXI_SAVE_INVALID')
            for point in ('origin','end'):
                p=flight[point]
                if not isinstance(p,dict) or any(type(p[k]) not in (int,float) or not math.isfinite(p[k]) or abs(p[k])>1000000 for k in ('x','y','z')):raise ValueError('TAXI_POSITION_INVALID')
            if any(type(flight[k]) not in (int,float) or not math.isfinite(flight[k]) or not 0<=flight[k]<=100000 for k in ('elapsed','duration')) or flight['duration']<1:raise ValueError('TAXI_CLOCK_INVALID')
        t=self._services['stuck_until']
        if type(t) not in (int,float) or not math.isfinite(t) or t<0:raise ValueError('STUCK_COOLDOWN_INVALID')

    def _travel_idle_locked(self):
        if self._opening_cinematic:raise ValueError('CINEMATIC_IN_PROGRESS')
        if self._services['battlefields']['active']:raise ValueError('BATTLEFIELD_IN_PROGRESS')
        if self._player_defeated_locked():raise ValueError('PLAYER_DEFEATED')
        if self._services['taxi_flight']:raise ValueError('TAXI_IN_PROGRESS')
        if self._services['stuck_cast']:raise ValueError('STUCK_CAST_IN_PROGRESS')
        if self._vehicle_kind!='NONE':raise ValueError('EXIT_VEHICLE_FIRST')
        if self._combat_state['actors'].get('player',{}).get('engaged_target'):raise ValueError('TRAVEL_OUT_OF_COMBAT_REQUIRED')

    def _travel_command_locked(self,row):
        op=row['op'];now=self._service_now_locked()
        if self._instance_private_locked() and op.startswith(('Taxi','Stuck')) and op not in ('TaxiClose','StuckCancel'):
            raise ValueError('INSTANCE_EXIT_REQUIRED')
        if op=='TaxiClose':self._service_windows['taxi']=None;return [{'event':'TAXIMAP_CLOSED','args':[]}]
        if op=='StuckCancel':
            if self._services['stuck_cast']:
                self._services['stuck_cast']=None;self._character_actions.pop('player',None)
                return [{'event':'SPELLCAST_INTERRUPTED','args':[]}]
            return []
        if op=='TaxiArrive':
            flight=self._services['taxi_flight']
            if not flight or flight['elapsed']<flight['duration']:raise ValueError('TAXI_NOT_AT_DESTINATION')
            self._lifecycle_move_locked(flight['end']);self._services['taxi_flight']=None
            self._resume_companion_locked(flight.get('pet_number',0))
            return []  # The original UI emits the transition from its confirmed snapshot.
        if op=='StuckFinish':
            cast=self._services['stuck_cast']
            if not cast or cast['elapsed']<10:raise ValueError('STUCK_CAST_NOT_COMPLETE')
            if self._player_defeated_locked() or self._combat_state['actors'].get('player',{}).get('engaged_target'):raise ValueError('STUCK_CAST_INTERRUPTED')
            bind=self._services['bind'];point=bind['position'] if bind else dict(x=0.,y=self._ground_contact_height_locked(0.,0.),z=0.)
            self._lifecycle_move_locked(point);self._services['stuck_cast']=None;self._services['stuck_until']=now+1800.
            self._start_character_action_locked('player','Idle');return [{'event':'SPELLCAST_STOP','args':[]}]
        self._travel_idle_locked()
        if op=='TaxiOpen':
            person=self._service_person_locked(row.get('target','target'),nearby=True)
            if person=='player':raise ValueError('TAXI_PROVIDER_REQUIRED')
            self._service_windows['taxi']=dict(person=person,origin=self._lifecycle_position_locked())
            return [{'event':'TAXIMAP_OPENED','args':[]}]
        if op=='TaxiTake':
            current=self._service_windows.get('taxi')
            if not current:raise ValueError('TAXI_MAP_CLOSED')
            self._service_person_locked(current['person'],nearby=True)
            if math.dist(tuple(current['origin'].values()),tuple(self._lifecycle_position_locked().values()))>3.:raise ValueError('TAXI_PROVIDER_MOVED')
            node=next((n for n in self._taxi_view_locked()['nodes'] if n['id']==row.get('destination')),None)
            if not node or node['current']:raise ValueError('TAXI_DESTINATION_UNAVAILABLE')
            self._service_money_locked(delta=-node['cost'])
            end=dict(x=node['x'],y=self._ground_contact_height_locked(node['x'],node['z']),z=node['z'])
            origin=self._lifecycle_position_locked();distance=math.dist(tuple(origin.values()),tuple(end.values()))
            self._services['taxi_flight']=dict(destination=node['id'],origin=origin,end=end,elapsed=0.,duration=max(1.,distance/40.),pet_number=self._suspend_companion_locked())
            self._services['stuck_cast']=None;self._service_windows['taxi']=None
            self._actions.auto_attack=False;self._clear_local_ui_sessions_locked();self._lifecycle_move_locked(origin)
            self._movement_mode='FLY';self._input['movement_mode']='FLY';self._grounded=False
            return [{'event':'TAXIMAP_CLOSED','args':[]}]
        if op=='SummonOffer':
            person=self._service_person_locked(row.get('target'))
            if person not in self._services['group']['members']:raise ValueError('SUMMON_GROUP_MEMBER_REQUIRED')
            index=self._npc_index_for_id_locked(person)
            if index is None or not self._alive[index] or not self._combat_state['actors'].get(person,{}).get('alive',True):raise ValueError('SUMMON_PROVIDER_UNAVAILABLE')
            self._service_windows['summon']=dict(person=person,expires=now+60.)
            return [{'event':'CONFIRM_SUMMON','args':[]}]
        if op=='SummonConfirm':
            pending=self._service_windows.get('summon')
            if not pending or pending['expires']<=now or pending['person'] not in self._services['group']['members']:raise ValueError('SUMMON_OFFER_EXPIRED')
            index=self._npc_index_for_id_locked(pending['person'])
            if index is None or not self._alive[index] or not self._combat_state['actors'].get(pending['person'],{}).get('alive',True):raise ValueError('SUMMON_PROVIDER_UNAVAILABLE')
            self._lifecycle_move_locked(dict(x=self._x[index]+1.,y=self._ground_contact_height_locked(self._x[index]+1.,self._z[index]),z=self._z[index]))
            self._service_windows['summon']=None;return [{'event':'PLAYER_CONTROL_GAINED','args':[]}]
        if op=='StuckStart':
            if now<self._services['stuck_until']:raise ValueError('STUCK_RECOVERY_COOLDOWN')
            self._services['stuck_cast']=dict(origin=self._lifecycle_position_locked(),elapsed=0.)
            self._start_character_action_locked('player','Enchant');self._character_actions['player']['until']=self._sim_time+10.;self._actions.auto_attack=False
            return [{'event':'SPELLCAST_START','args':['Recovery',10000]}]
        raise ValueError('TRAVEL_COMMAND_UNKNOWN')

    def _taxi_view_locked(self):
        current=self._service_windows.get('taxi');flight=self._services['taxi_flight'];pending=self._service_windows.get('summon')
        now=max(float(self._services['clock']),time.time());summon=dict(summoner='',area='',remaining_ms=0)
        if pending and pending['expires']>now:
            summon=dict(summoner=self._service_unit_locked(pending['person'])['name'],area='GG World',remaining_ms=int((pending['expires']-now)*1000))
        out=dict(open=bool(current),nodes=[],riding=bool(flight),remaining=max(0.,flight['duration']-flight['elapsed']) if flight else 0.,summon=summon,
                 stuck_remaining=max(0.,10-self._services['stuck_cast']['elapsed']) if self._services['stuck_cast'] else 0.)
        if not current:return out
        try:self._service_person_locked(current['person'],nearby=True)
        except ValueError:self._service_windows['taxi']=None;out['open']=False;return out
        nodes=self._travel_nodes_locked();origin=current['origin'];nearest=min(nodes,key=lambda r:math.hypot(r['x']-origin['x'],r['z']-origin['z']))
        extent=max(1.,max(max(abs(r['x']),abs(r['z'])) for r in nodes))
        for row in nodes:
            distance=math.hypot(row['x']-origin['x'],row['z']-origin['z']);is_current=row['id']==nearest['id']
            out['nodes'].append(dict(row,current=is_current,cost=0 if is_current else max(100,int(math.ceil(distance/10.))),
                position=[.5+row['x']/extent*.45,.5-row['z']/extent*.45],source=[.5+origin['x']/extent*.45,.5-origin['z']/extent*.45]))
        return out

    def _tick_travel_locked(self,dt):
        flight=self._services['taxi_flight'];cast=self._services['stuck_cast']
        if self._player_defeated_locked():self._services['taxi_flight']=self._services['stuck_cast']=None;return
        if flight:
            flight['elapsed']=min(flight['duration'],flight['elapsed']+max(0.,dt));f=flight['elapsed']/flight['duration']
            p={k:flight['origin'][k]*(1-f)+flight['end'][k]*f for k in ('x','y','z')}
            if f<1:
                p['y']=max(p['y']+math.sin(math.pi*f)*35.,self._terrain_height_locked(p['x'],p['z'])+4.)
                self._x[0],self._y[0],self._z[0]=(p[k] for k in ('x','y','z'));self._vx[0]=self._vy[0]=self._vz[0]=0.
                self._yaw[0]=math.atan2(flight['end']['x']-flight['origin']['x'],flight['end']['z']-flight['origin']['z'])
                self._movement_mode='FLY';self._input['movement_mode']='FLY';self._grounded=False
            else:
                try:self._service_command_locked(dict(op='TaxiArrive'))
                except (OSError,ValueError):return
            self._render_snapshot_cache=None;self._ui_snapshot_base=None
        if cast:
            if math.dist(tuple(cast['origin'].values()),tuple(self._lifecycle_position_locked().values()))>.75 or self._combat_state['actors'].get('player',{}).get('engaged_target'):
                self._services['stuck_cast']=None;self._character_actions.pop('player',None);return
            cast['elapsed']+=max(0.,dt)
            if cast['elapsed']>=10:
                try:self._service_command_locked(dict(op='StuckFinish'))
                except (OSError,ValueError):return
