"""Owned private expedition maps and group finding at authored GG places.

Each local place has isolated encounters and ground custody. Acquired items
remain in the same canonical registry when crossing a map boundary.
"""
import copy
import math
import time
from backend import game_engine_world_places as places,game_engine_combat as combat,game_engine_items as items
from backend.game_engine_adapter_gameplay import identity
from backend.game_engine_adapter_local_client import integer
from backend.game_engine_adapter_private_world import PrivateWorldMixin

BOUNDARY=24.


def defaults():return dict(instance_sessions=dict(active=None,lockouts=[],resets=[],meeting=None,overworld=None,item_maps={}))


def finite(value,limit=2**40):
    if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=limit:raise ValueError('INSTANCE_CLOCK_INVALID')
    return float(value)


class InstanceSessionsMixin(PrivateWorldMixin):
    def _expedition_places_locked(self):
        return {row['id']:row for row in places.catalog()['places'] if row['kind'] in ('RUINS','WORKS')}

    def _restore_instance_sessions_locked(self):
        state=self._services.setdefault('instance_sessions',defaults()['instance_sessions'])
        if not isinstance(state,dict):raise ValueError('INSTANCE_SAVE_INVALID')
        state.setdefault('overworld',None);state.setdefault('item_maps',{})
        if set(state)!=set(('active','lockouts','resets','meeting','overworld','item_maps')):raise ValueError('INSTANCE_SAVE_INVALID')
        if not isinstance(state['lockouts'],list) or len(state['lockouts'])>32 or not isinstance(state['resets'],list) or len(state['resets'])>5:
            raise ValueError('INSTANCE_SAVE_CAPACITY')
        refs=set();keys=set();known=self._expedition_places_locked();people=self._individual_state.get('individuals',{})
        for row in state['lockouts']:
            key=integer(row['id'],1,self._services['next_id']-1);ref=row['ref']
            if key in keys or ref in refs or ref not in known or row['type'] not in (1,2):raise ValueError('INSTANCE_LOCKOUT_INVALID')
            keys.add(key);refs.add(ref);finite(row['expires'])
            crew=row['participants'];defeated=row['defeated']
            if (not isinstance(crew,list) or not 1<=len(crew)<=40 or crew[0]!='player' or len(set(crew))!=len(crew)
                    or any(p!='player' and p not in people for p in crew) or not isinstance(defeated,list) or len(defeated)>64
                    or len(set(defeated))!=len(defeated) or any(p not in people for p in defeated)):
                raise ValueError('INSTANCE_PARTICIPANTS_INVALID')
        for value in state['resets']:finite(value)
        active=state['active']
        if active:
            if not isinstance(active,dict) or active['id'] not in keys:raise ValueError('INSTANCE_ACTIVE_INVALID')
            point=active['origin']
            if not isinstance(point,dict) or set(point)!=set(('x','y','z')) or any(type(v) not in (int,float) or not math.isfinite(v) or abs(v)>1000000 for v in point.values()):
                raise ValueError('INSTANCE_POSITION_INVALID')
        self._instance_validate_worlds_locked(state,known)
        # Pending recruitment cannot consent on behalf of a fresh login.
        state['meeting']=None

    def _instance_npc_index_locked(self,owner):
        return next((i for i in self._npc_indices if self._alive[i] and self._npc_ids[i]==owner),None)

    def _expedition_record_locked(self):
        state=self._services['instance_sessions'];active=state['active']
        return next((r for r in state['lockouts'] if active and r['id']==active['id']),None)

    def _instance_near_place_locked(self,ref,radius):
        place=self._expedition_places_locked().get(ref)
        if not place:raise ValueError('INSTANCE_PLACE_NOT_LOCAL')
        return math.hypot(self._x[0]-place['x'],self._z[0]-place['z'])<=radius

    def _instance_group_owner_locked(self):
        group=self._services['group']
        if group['members'] and group['leader']!='player':raise ValueError('INSTANCE_GROUP_LEADER_REQUIRED')

    def _instance_occupied_locked(self,record):
        if record.get('world'):
            active=self._services['instance_sessions']['active']
            return bool(active and active['id']==record['id'])
        place=self._expedition_places_locked()[record['ref']]
        for owner in record['participants']:
            index=0 if owner=='player' else self._instance_npc_index_locked(owner)
            if index is not None and math.hypot(self._x[index]-place['x'],self._z[index]-place['z'])<=BOUNDARY:return True
        return False

    def _instance_command_locked(self,row):
        from backend.game_engine_adapter_services import events
        state=self._services['instance_sessions'];op=row['op'];now=self._service_now_locked()
        if op=='InstanceExit':
            active=state['active']
            if not active:raise ValueError('INSTANCE_NOT_ACTIVE')
            if self._player_defeated_locked() and not self._is_ghost_locked():raise ValueError('PLAYER_DEFEATED')
            if self._combat_state['actors'].get('player',{}).get('engaged_target'):raise ValueError('INSTANCE_OUT_OF_COMBAT_REQUIRED')
            self._instance_exit_world_locked()
            self._lifecycle_move_locked(active['origin']);state['active']=None
            return events('ZONE_CHANGED_NEW_AREA')
        if op=='InstanceLeaveArea':
            record=self._expedition_record_locked()
            if not record or self._instance_near_place_locked(record['ref'],BOUNDARY+16.):raise ValueError('INSTANCE_STILL_INSIDE')
            if self._player_defeated_locked() and not self._is_ghost_locked():raise ValueError('PLAYER_DEFEATED')
            if self._combat_state['actors'].get('player',{}).get('engaged_target'):raise ValueError('INSTANCE_OUT_OF_COMBAT_REQUIRED')
            origin=state['active']['origin'];self._instance_exit_world_locked()
            self._lifecycle_move_locked(origin)
            state['active']=None;return events('ZONE_CHANGED_NEW_AREA')
        if op=='InstanceEnter':
            ghost=self._is_ghost_locked()
            if ghost:
                # A released character can return only to their own saved
                # corpse map, never open another expedition while dead.
                death=self._services['death'];record=next((r for r in state['lockouts'] if r['ref']==row.get('ref')),None)
                if not record or death.get('instance_id',0)!=record['id']:raise ValueError('CORPSE_INSTANCE_REQUIRED')
                if self._services['taxi_flight'] or self._services['stuck_cast'] or self._vehicle_kind!='NONE':raise ValueError('INSTANCE_TRAVEL_BUSY')
            else:self._travel_idle_locked();self._instance_group_owner_locked()
            if self._services['duel']:raise ValueError('DUEL_IN_PROGRESS')
            ref=row.get('ref')
            if not isinstance(ref,str) or not self._instance_near_place_locked(ref,64.):raise ValueError('INSTANCE_ENTRANCE_OUT_OF_REACH')
            if state['active']:
                if self._expedition_record_locked()['ref']==ref:return []
                raise ValueError('INSTANCE_ALREADY_ACTIVE')
            record=next((r for r in state['lockouts'] if r['ref']==ref),None)
            if not record:
                if len(state['lockouts'])>=32:raise ValueError('INSTANCE_LOCKOUT_CAPACITY')
                record=dict(id=self._service_id_locked(),ref=ref,type=2 if self._services['group']['raid'] else 1,
                    expires=now+(7*86400 if self._services['group']['raid'] else 86400),
                    participants=['player']+list(self._services['group']['members']),defeated=[])
                state['lockouts'].append(record)
            if record['expires']<=now:raise ValueError('INSTANCE_RESET_REQUIRED')
            place=self._expedition_places_locked()[ref];origin=self._lifecycle_position_locked()
            x,z=place['x']+18.,place['z']
            self._instance_enter_world_locked(record)
            self._lifecycle_move_locked(dict(x=x,y=self._ground_contact_height_locked(x,z),z=z))
            state['active']=dict(id=record['id'],origin=origin)
            return events('ZONE_CHANGED_NEW_AREA')+events('UPDATE_INSTANCE_INFO')
        if op=='InstanceEncounter':
            record=self._expedition_record_locked();owner=row.get('target');index=self._instance_npc_index_locked(owner)
            actor=self._combat_state['actors'].get(owner,{})
            if not record or index is None or actor.get('alive',True):raise ValueError('INSTANCE_DEFEAT_REQUIRED')
            place=self._expedition_places_locked()[record['ref']]
            if math.hypot(self._x[index]-place['x'],self._z[index]-place['z'])>BOUNDARY:raise ValueError('INSTANCE_ENCOUNTER_OUT_OF_BOUNDS')
            attacker=actor.get('last_hit_by','')
            if attacker not in record['participants'] and not str(attacker).startswith('pet:'):raise ValueError('INSTANCE_KILL_CREDIT_REQUIRED')
            if owner not in record['defeated']:
                if len(record['defeated'])>=64:raise ValueError('INSTANCE_ENCOUNTER_CAPACITY')
                record['defeated'].append(owner)
            return events('UPDATE_INSTANCE_INFO')
        if op=='InstanceReset':
            self._instance_group_owner_locked()
            if state['active']:raise ValueError('INSTANCE_INSIDE')
            requested=row.get('ref')
            records=[r for r in state['lockouts'] if requested is None or requested==r['ref']]
            if requested is not None and not records:raise ValueError('INSTANCE_NOT_OWNED')
            targets=[r for r in records if r['type']==1 or r['expires']<=now]
            if requested is not None and not targets:raise ValueError('INSTANCE_RAID_LOCKED')
            if any(self._instance_occupied_locked(r) for r in targets):raise ValueError('INSTANCE_OCCUPIED')
            times=[t for t in state['resets'] if now-t<3600.]
            if targets and len(times)>=5:raise ValueError('INSTANCE_RESET_LIMIT')
            for record in targets:
                if record.get('world'):
                    world_ids=[key for key,value in state['item_maps'].items() if value==record['id']]
                    if any(self._item_instances[key].get('location') in ('GROUND','CONTAINER')
                           and self._item_instances[key].get('loot_claimed')
                           for key in world_ids if key in self._item_instances):
                        raise ValueError('INSTANCE_OWNED_ITEMS_LEFT_BEHIND')
                    for key in world_ids:
                        item=self._item_instances.get(key)
                        if item and item.get('location') in ('GROUND','CONTAINER'):
                            items.transition_instance(item,'DESTROYED')
                        state['item_maps'].pop(key,None)
                    state['lockouts'].remove(record)
                    continue
                for owner in record['defeated']:
                    index=self._instance_npc_index_locked(owner);actor=self._combat_state['actors'].get(owner)
                    if index is None or not actor or actor.get('alive',True):continue
                    actor['respawn_at']=min(self._sim_time,actor.get('respawn_at',self._sim_time))
                    combat.respawn_actor(self._combat_state,owner,self._npc_combat_profile_locked(owner),self._sim_time)
                    self._vx[index]=self._vy[index]=self._vz[index]=0.
                    self._npc_state[index]='WANDER';self._npc_reason[index]='INSTANCE_RESET'
                    self._character_actions.pop(owner,None)
                for item in self._item_instances.values():
                    if item.get('location')=='GROUND' and item.get('source_actor_id') in record['defeated'] and not item.get('loot_claimed'):
                        items.transition_instance(item,'DESTROYED')
                state['lockouts'].remove(record)
            if targets:times.append(now)
            state['resets']=times[-5:]
            return events('UPDATE_INSTANCE_INFO')+events('CHAT_MSG_SYSTEM',f'{len(targets)} local GG expedition(s) reset; acquired items remain in their actual custody.')
        if op.startswith('MeetingStone'):return self._meeting_stone_command_locked(row)
        raise ValueError('INSTANCE_COMMAND_UNKNOWN')

    def _meeting_stone_command_locked(self,row):
        from backend.game_engine_adapter_services import events
        state=self._services['instance_sessions'];op=row['op'];meeting=state['meeting'];now=self._service_now_locked()
        if op=='MeetingStoneCancel':
            state['meeting']=None
            return events('MEETINGSTONE_CHANGED')
        if op=='MeetingStoneJoin':
            self._travel_idle_locked()
            if state['active'] or self._services['group']['members']:raise ValueError('MEETINGSTONE_SOLO_REQUIRED')
            if meeting:raise ValueError('MEETINGSTONE_ALREADY_QUEUED')
            ref=row.get('ref')
            if not isinstance(ref,str) or not self._instance_near_place_locked(ref,64.):raise ValueError('MEETINGSTONE_OUT_OF_REACH')
            state['meeting']=dict(ref=ref,area=identity('gg.instance.'+ref),created_at=now,expires=now+60.,stage='QUEUED',candidates=[])
            return events('MEETINGSTONE_CHANGED')
        if not meeting or now>=meeting['expires']:raise ValueError('MEETINGSTONE_REQUEST_EXPIRED')
        if op=='MeetingStoneOffer':
            if now-meeting['created_at']<3 or meeting['stage']!='QUEUED':raise ValueError('MEETINGSTONE_NOT_READY')
            candidates=[]
            for owner,person in self._individual_state.get('individuals',{}).items():
                if person.get('role') not in ('GUARDIAN','FISHER','WANDERER','EXPLORER'):continue
                try:self._service_person_locked(owner,nearby=True)
                except ValueError:continue
                candidates.append(owner)
            if not candidates:raise ValueError('MEETINGSTONE_NO_LOCAL_COMPANIONS')
            meeting.update(stage='OFFER',candidates=candidates[:4])
            return events('MEETINGSTONE_CHANGED')
        if op=='MeetingStoneAccept':
            if self._services['group']['members'] or meeting['stage']!='OFFER':raise ValueError('MEETINGSTONE_OFFER_REQUIRED')
            if not self._instance_near_place_locked(meeting['ref'],64.):raise ValueError('MEETINGSTONE_OUT_OF_REACH')
            crew=list(meeting['candidates'])
            for owner in crew:self._service_person_locked(owner,nearby=True)
            result=[]
            for owner in crew:result+=self._group_command_locked(dict(op='GroupInvite',target=owner))
            state['meeting']=None
            return result+events('MEETINGSTONE_CHANGED')
        raise ValueError('MEETINGSTONE_COMMAND_UNKNOWN')

    def _instance_encounter_locked(self,owner):
        record=self._expedition_record_locked()
        return bool(record and owner in record['defeated'])

    def _instance_sessions_view_locked(self):
        state=self._services['instance_sessions'];now=max(self._services['clock'],time.time());places=self._expedition_places_locked()
        record=self._expedition_record_locked();group=self._services['group'];leader=not group['members'] or group['leader']=='player'
        lockouts=[dict(r,name=places[r['ref']]['name'],remaining=max(0,int(r['expires']-now))) for r in state['lockouts']]
        meeting=copy.deepcopy(state['meeting'])
        if meeting:meeting['name']=places[meeting['ref']]['name'];meeting['remaining']=max(0,int(meeting['expires']-now))
        return dict(active=copy.deepcopy(state['active']),type=record['type'] if record else 0,map=self._instance_map_descriptor_locked(),isolated=self._instance_private_locked(),
                    can_reset=bool(leader and not record and any(r['type']==1 and not self._instance_occupied_locked(r) for r in state['lockouts'])),
                    lockouts=lockouts,meeting=meeting,
                    places=[dict(id=p['id'],name=p['name'],distance=round(math.hypot(self._x[0]-p['x'],self._z[0]-p['z']),1)) for p in places.values()])

    def _tick_instance_sessions_locked(self):
        state=self._services['instance_sessions'];record=self._expedition_record_locked();now=self._service_now_locked()
        if record:
            if not self._instance_near_place_locked(record['ref'],BOUNDARY+16.):
                try:self._service_command_locked(dict(op='InstanceLeaveArea'))
                except (ValueError,OSError):pass
                return
            for owner,actor in list(self._combat_state.get('actors',{}).items()):
                if not actor.get('alive',True) and owner!='player' and owner not in record['defeated']:
                    try:self._service_command_locked(dict(op='InstanceEncounter',target=owner))
                    except (ValueError,OSError):pass
        meeting=self._services['instance_sessions']['meeting']
        if meeting:
            if now>=meeting['expires'] or self._services['group']['members']:command=dict(op='MeetingStoneCancel')
            elif meeting['stage']=='QUEUED' and now-meeting['created_at']>=3:command=dict(op='MeetingStoneOffer')
            else:return
            try:self._service_command_locked(command)
            except (ValueError,OSError):pass
