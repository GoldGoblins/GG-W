"""Local GG practice arena over the existing actors, combat and duel rules.

This is an authored GG match, not a remote battleground. Nonlethal NPC
victories award local bonus honor; they never invent honorable player kills,
loot, XP, a remote rank or another copy of a character.
"""
import copy
import math
from datetime import datetime,timezone
from backend.game_engine_adapter_local_client import integer

MAP_ID=0x4701
MAP_NAME='GG Kustarenan'
INSTANCE_ID=1


def defaults():
    return dict(battlefields=dict(queue=[],active=None,last_scores=None,cooldown_until=0.),honor_ledger={})


def stamp(value):
    if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=2**40:
        raise ValueError('BATTLEFIELD_CLOCK_INVALID')
    return float(value)


def point(value):
    if not isinstance(value,dict) or set(value)!=set(('x','y','z')):raise ValueError('BATTLEFIELD_POSITION_INVALID')
    if any(type(v) not in (int,float) or not math.isfinite(v) or abs(v)>1_000_000 for v in value.values()):raise ValueError('BATTLEFIELD_POSITION_INVALID')
    return dict(value)


class BattlefieldsMixin:
    def _restore_battlefields_locked(self):
        self._battlefield_cancelled_return=None
        for key,value in defaults().items():self._services.setdefault(key,copy.deepcopy(value))
        state=self._services['battlefields'];ledger=self._services['honor_ledger']
        if not isinstance(state,dict) or not isinstance(state.get('queue'),list) or len(state['queue'])>3:
            raise ValueError('BATTLEFIELD_SAVE_CAPACITY')
        stamp(state['cooldown_until']);seen=set()
        for row in state['queue']:
            key=integer(row['id'],1,self._services['next_id']-1)
            if key in seen or row['map']!=MAP_ID or type(row['status']) is not int or row['status'] not in (1,2,3):raise ValueError('BATTLEFIELD_QUEUE_INVALID')
            seen.add(key);stamp(row['queued_at']);stamp(row['ready_at']);stamp(row['deadline'])
            if type(row['as_group']) is not bool:raise ValueError('BATTLEFIELD_QUEUE_INVALID')
        if not isinstance(ledger,dict) or len(ledger)>64:raise ValueError('HONOR_LEDGER_CAPACITY')
        for owner,days in ledger.items():
            if (not isinstance(owner,str) or len(owner)>64 or owner!='player' and owner not in self._individual_state.get('individuals',{})
                    or not isinstance(days,dict) or len(days)>16):raise ValueError('HONOR_LEDGER_INVALID')
            for day,row in days.items():
                datetime.strptime(day,'%Y-%m-%d')
                if not isinstance(row,dict) or set(row)!=set(('honor','wins','losses')):raise ValueError('HONOR_LEDGER_INVALID')
                for value in row.values():integer(value,0,2**32-1)
        if state['last_scores'] is not None:self._validate_battlefield_scores_locked(state['last_scores'])
        active=state['active']
        if active is not None:
            if not isinstance(active,dict) or active['queue_id'] not in seen or active['state'] not in ('ACTIVE','ENDED'):
                raise ValueError('BATTLEFIELD_MATCH_INVALID')
            if active['opponent'] not in self._individual_state.get('individuals',{}):raise ValueError('BATTLEFIELD_OPPONENT_INVALID')
            point(active['opponent_origin']);point(active['origin']);stamp(active['started_at'])
            self._validate_battlefield_scores_locked(active['scores'],active['opponent'])
            if active['state']=='ENDED':integer(active['winner'],0,1)
            # A fresh login requires fresh NPC consent and never awards a saved
            # unfinished match. Preserve its result board, cancel its live slot.
            self._battlefield_cancelled_return=dict(opponent=active['opponent'],opponent_origin=point(active['opponent_origin']))
            state['last_scores']=copy.deepcopy(active['scores']);state['active']=None;state['queue']=[]
        self._battlefield_map=0;self._battlefield_positions_at=0.
        self._inspect_honor_owner=None

    def _validate_battlefield_scores_locked(self,board,opponent=None):
        people=self._individual_state.get('individuals',{})
        if not isinstance(board,dict) or not 1<=len(board)<=2 or 'player' not in board:
            raise ValueError('BATTLEFIELD_SCORE_INVALID')
        if opponent is not None and set(board)!=set(('player',opponent)):
            raise ValueError('BATTLEFIELD_SCORE_INVALID')
        for owner,row in board.items():
            if owner!='player' and owner not in people:raise ValueError('BATTLEFIELD_SCORE_INVALID')
            if not isinstance(row,dict) or set(row)!=set(('honor','wins','deaths')):raise ValueError('BATTLEFIELD_SCORE_INVALID')
            for value in row.values():integer(value,0,2**32-1)

    def _battlefield_loaded_locked(self):
        # World arrays and combat ownership must be loaded before returning
        # the actual resident to its pre-arena position after fresh login.
        pending=getattr(self,'_battlefield_cancelled_return',None)
        if pending:self._battlefield_return_opponent_locked(pending)
        self._battlefield_cancelled_return=None

    def _battlefield_command_locked(self,row):
        from backend.game_engine_adapter_services import events
        op=row['op'];state=self._services['battlefields'];now=self._service_now_locked()
        if op=='BattlefieldList':
            if integer(row.get('map'),1,2**32-1)!=MAP_ID:raise ValueError('BATTLEFIELD_MAP_NOT_LOCAL')
            self._battlefield_map=MAP_ID
            return events('BATTLEFIELDS_SHOW')
        if op=='BattlefieldJoin':
            if self._instance_private_locked():raise ValueError('INSTANCE_EXIT_REQUIRED')
            self._travel_idle_locked()
            if self._services['duel'] or state['active']:raise ValueError('BATTLEFIELD_MATCH_IN_PROGRESS')
            if now<state['cooldown_until']:raise ValueError('BATTLEFIELD_RECOVERY_REQUIRED')
            if integer(row.get('map'),1,2**32-1)!=MAP_ID or integer(row.get('instance',0),0,2**32-1) not in (0,INSTANCE_ID):
                raise ValueError('BATTLEFIELD_INSTANCE_NOT_LOCAL')
            if type(row.get('as_group',False)) is not bool:raise ValueError('BATTLEFIELD_GROUP_INVALID')
            if row.get('as_group') and (not self._services['group']['members'] or self._services['group']['leader']!='player'):
                raise ValueError('BATTLEFIELD_GROUP_LEADER_REQUIRED')
            if state['queue']:return []
            self._battlefield_opponent_locked()
            key=self._service_id_locked()
            state['queue'].append(dict(id=key,map=MAP_ID,status=1,queued_at=now,ready_at=now+3.,deadline=0.,as_group=row.get('as_group',False)))
            return events('UPDATE_BATTLEFIELD_STATUS',1)
        if op=='BattlefieldReady':
            queued=self._battlefield_slot_locked(row)
            if queued['status']!=1 or now<queued['ready_at']:raise ValueError('BATTLEFIELD_QUEUE_NOT_READY')
            queued.update(status=2,deadline=now+60.)
            return events('UPDATE_BATTLEFIELD_STATUS',1)
        if op=='BattlefieldPort':
            queued=self._battlefield_slot_locked(row)
            if type(row.get('accept')) is not bool:raise ValueError('BATTLEFIELD_ANSWER_INVALID')
            if not row['accept']:
                active=state['active']
                if active and active['queue_id']==queued['id']:
                    if self._services['duel']:self._duel_command_locked(dict(op='DuelCancel'))
                    self._battlefield_return_opponent_locked(active);state['active']=None
                state['queue'].remove(queued)
                return events('UPDATE_BATTLEFIELD_STATUS',1)
            if queued['status']!=2 or now>=queued['deadline']:raise ValueError('BATTLEFIELD_PORT_EXPIRED')
            self._travel_idle_locked()
            if self._services['duel']:raise ValueError('DUEL_UNAVAILABLE')
            opponent=self._battlefield_opponent_locked();index=self._npc_index_for_id_locked(opponent)
            origin={k:float(getattr(self,'_'+k)[index]) for k in ('x','y','z')}
            self._x[index]=self._x[0]+2.;self._z[index]=self._z[0]
            self._y[index]=self._ground_contact_height_locked(self._x[index],self._z[index])
            self._vx[index]=self._vy[index]=self._vz[index]=0.
            result=self._duel_command_locked(dict(op='DuelStart',target=opponent))
            state['active']=dict(queue_id=queued['id'],state='ACTIVE',opponent=opponent,opponent_origin=origin,
                origin=self._lifecycle_position_locked(),started_at=now,result=None,
                scores={owner:dict(honor=0,wins=0,deaths=0) for owner in ('player',opponent)})
            queued['status']=3
            return result+events('UPDATE_BATTLEFIELD_SCORE')+events('UPDATE_BATTLEFIELD_STATUS',1)
        if op=='BattlefieldFinish':
            active=state['active'];result=active.get('result') if active else None
            if not active or active['state']!='ACTIVE' or not result:raise ValueError('BATTLEFIELD_RESULT_REQUIRED')
            winner=result['winner'];loser=active['opponent'] if winner=='player' else 'player'
            active['state']='ENDED';active['winner']=1 if winner=='player' else 0
            active['scores'][winner]['wins']=1
            if result['reason']=='VICTORY':
                active['scores'][winner]['honor']=10
                self._record_arena_honor_locked(winner,loser,10,now)
            state['cooldown_until']=now+30.
            return events('UPDATE_BATTLEFIELD_SCORE')+events('UPDATE_BATTLEFIELD_STATUS',1)+events('PLAYER_PVP_KILLS_CHANGED')
        if op=='BattlefieldTimeout':
            active=state['active']
            if not active or active['state']!='ACTIVE' or now-active['started_at']<180.:raise ValueError('BATTLEFIELD_NOT_TIMED_OUT')
            if self._services['duel']:return self._duel_end_locked(active['opponent'],'TIMEOUT')
            return []
        if op=='BattlefieldLeave':
            active=state['active']
            if not active or active['state']!='ENDED':raise ValueError('BATTLEFIELD_NOT_ENDED')
            state['last_scores']=copy.deepcopy(active['scores'])
            self._battlefield_return_opponent_locked(active);state['active']=None;state['queue']=[]
            return events('UPDATE_BATTLEFIELD_STATUS',1)
        if op=='BattlefieldPositions':
            if not state['active']:raise ValueError('BATTLEFIELD_ACTIVE_REQUIRED')
            self._battlefield_positions_at=now
            return []
        if op=='BattlefieldScore':return events('UPDATE_BATTLEFIELD_SCORE')
        if op=='InspectHonor':
            inspect=self._service_windows.get('inspection')
            if not inspect:raise ValueError('INSPECT_TARGET_OUT_OF_REACH')
            self._inspect_person_locked(inspect['person'])
            self._inspect_honor_owner=inspect['person'];return []
        raise ValueError('BATTLEFIELD_COMMAND_UNKNOWN')

    def _battlefield_slot_locked(self,row):
        slot=integer(row.get('slot',1),1,3)-1;rows=self._services['battlefields']['queue']
        if slot>=len(rows) or integer(row.get('queue_id'),1,2**31-1)!=rows[slot]['id']:raise ValueError('BATTLEFIELD_QUEUE_CHANGED')
        return rows[slot]

    def _battlefield_opponent_locked(self):
        # Use a living authored resident with combat capability, never a second
        # actor, a merchant's wallet or an invented opponent roster.
        for owner,person in self._individual_state.get('individuals',{}).items():
            index=self._npc_index_for_id_locked(owner)
            if (index is not None and self._combat_state['actors'].get(owner,{}).get('alive',True)
                    and not self._combat_state['actors'].get(owner,{}).get('engaged_target')
                    and person.get('role') in ('GUARDIAN','GUARD','WARRIOR','SENTINEL')):
                return owner
        raise ValueError('BATTLEFIELD_NO_LOCAL_OPPONENT')

    def _battlefield_return_opponent_locked(self,active):
        owner=active['opponent'];index=self._npc_index_for_id_locked(owner)
        if index is not None:
            for axis,value in active['opponent_origin'].items():getattr(self,'_'+axis)[index]=value
            self._vx[index]=self._vy[index]=self._vz[index]=0.
        self._combat_state['actors'].get(owner,{}).update(engaged_target='')

    def _battlefield_duel_result_locked(self,winner,reason):
        active=self._services['battlefields']['active'];duel=self._services['duel']
        if not active or active['state']!='ACTIVE' or not duel or duel['target']!=active['opponent']:return
        if winner not in ('player',active['opponent']):raise ValueError('BATTLEFIELD_WINNER_INVALID')
        if reason=='VICTORY' and self._combat_state.get('duel',{}).get('loser') not in ('player',active['opponent']):
            raise ValueError('BATTLEFIELD_COMBAT_RESULT_REQUIRED')
        active['result']=dict(winner=winner,reason=reason)

    def _record_arena_honor_locked(self,winner,loser,honor,now):
        day=datetime.fromtimestamp(now,timezone.utc).strftime('%Y-%m-%d')
        for owner in (winner,loser):
            rows=self._services['honor_ledger'].setdefault(owner,{})
            row=rows.setdefault(day,dict(honor=0,wins=0,losses=0))
            row['wins' if owner==winner else 'losses']+=1
            if owner==winner:row['honor']+=honor
            for old in sorted(rows)[:-16]:del rows[old]

    def _honor_view_locked(self,owner,now):
        today=datetime.fromtimestamp(now,timezone.utc).date();week=today.isocalendar()[:2]
        yesterday_honor=this_week_honor=last_week_honor=0
        for day,row in self._services['honor_ledger'].get(owner,{}).items():
            date=datetime.strptime(day,'%Y-%m-%d').date();difference=(today-date).days
            if difference==1:yesterday_honor+=row['honor']
            if date.isocalendar()[:2]==week:this_week_honor+=row['honor']
            elif 1<=difference<=14 and (today.toordinal()-today.weekday()-7)<=date.toordinal()<today.toordinal()-today.weekday():last_week_honor+=row['honor']
        return dict(yesterday_honor=yesterday_honor,this_week_honor=this_week_honor,last_week_honor=last_week_honor)

    def _battlefields_view_locked(self):
        state=self._services['battlefields'];active=state['active'];now=max(self._services['clock'],__import__('time').time())
        queue=[dict(row,remaining_ms=max(0,int((row['deadline']-now)*1000)),waited_ms=max(0,int((now-row['queued_at'])*1000))) for row in state['queue']]
        board=active['scores'] if active else state['last_scores'] or {}
        scores=[dict(id=owner,name=self._service_unit_locked(owner)['name'],team=1 if owner=='player' else 0,
                     **row) for owner,row in board.items()]
        honor=self._honor_view_locked('player',now);inspect=None
        current=self._service_windows.get('inspection')
        if current and current['person']==self._inspect_honor_owner and self._inspect_honor_owner and self._lifecycle_near_locked(self._inspect_honor_owner):
            inspect=dict(guid=self._service_unit_locked(self._inspect_honor_owner)['guid'],**self._honor_view_locked(self._inspect_honor_owner,now))
        return dict(map=MAP_ID,name=MAP_NAME,instance=INSTANCE_ID,listed=getattr(self,'_battlefield_map',0)==MAP_ID,
                    description='Local GG nonlethal practice. Bonus honor for a real combat victory; no player-kill credit, loot or XP.',
                    queue=queue,active=bool(active),ended=bool(active and active['state']=='ENDED'),scores=scores,
                    winner=(active or {}).get('winner',0),run_ms=int(max(0,now-active['started_at'])*1000) if active else 0,
                    positions=[],honor=honor,inspect=inspect,recovery_seconds=max(0,math.ceil(state['cooldown_until']-now)))

    def _tick_battlefields_locked(self):
        state=self._services['battlefields'];now=self._service_now_locked()
        for row in list(state['queue']):
            command=None
            if row['status']==1 and now>=row['ready_at']:command=dict(op='BattlefieldReady',slot=1,queue_id=row['id'])
            elif row['status']==2 and now>=row['deadline']:command=dict(op='BattlefieldPort',slot=1,queue_id=row['id'],accept=False)
            if command:
                try:self._service_command_locked(command)
                except (ValueError,OSError):pass
        active=self._services['battlefields']['active']
        if active and active['state']=='ACTIVE' and not active['result'] and now-active['started_at']>=180.:
            try:self._service_command_locked(dict(op='BattlefieldTimeout'))
            except (ValueError,OSError):pass
        if active and active['state']=='ACTIVE' and active['result']:
            try:self._service_command_locked(dict(op='BattlefieldFinish'))
            except (ValueError,OSError):pass
