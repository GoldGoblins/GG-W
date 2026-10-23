"""Corpse/release/resurrection, bind points and bounded local duels.

All transitions use the host's existing actor, position and character store.
Wall-clock deadlines survive a fresh process; simulation damage remains fixed-step.
"""
import copy
import math
import time
from backend import game_engine_combat as combat, game_engine_items as items


def defaults():
    return dict(death=None, bind=None, sickness_until=0., duel=None)


class LifecycleMixin:
    def _player_defeated_locked(self):
        return not self._combat_state.get('actors',{}).get('player',{}).get('alive',True)

    def _is_ghost_locked(self):
        death=getattr(self,'_services',{}).get('death')
        return bool(death and death.get('ghost'))

    def _restore_lifecycle_locked(self):
        for k,v in defaults().items():self._services.setdefault(k,copy.deepcopy(v))
        for key in ('bind','death'):
            row=self._services[key]
            if row is None:continue
            if not isinstance(row,dict):raise ValueError('INVALID_LIFECYCLE')
            p=row['position']
            if not isinstance(p,dict) or any(type(p.get(k)) not in (int,float) or not math.isfinite(p[k]) or abs(p[k])>1000000 for k in ('x','y','z')):raise ValueError('INVALID_LIFECYCLE_POSITION')
        death=self._services['death']
        if death:
            if type(death['ghost']) is not bool or any(type(death.get(k)) not in (int,float) or not math.isfinite(death[k]) or death[k]<0 for k in ('release_at','recover_at')):raise ValueError('INVALID_DEATH')
            death['offer']=None;death['healer']='' # transient dialogs cannot survive login.
            yaw=death.get('yaw',0.);serial=death.get('serial',1)
            if type(yaw) not in (int,float) or not math.isfinite(yaw) or abs(yaw)>1e9 or type(serial) is not int or not 0<=serial<=2_000_000_000:raise ValueError('INVALID_CORPSE_POSE')
            for key in ('map_id','instance_id'):
                value=death.get(key,0)
                if type(value) is not int or not 0<=value<2**31:raise ValueError('INVALID_CORPSE_MAP')
        value=self._services['sickness_until']
        if type(value) not in (int,float) or not math.isfinite(value) or value<0:raise ValueError('INVALID_SICKNESS')
        # An opponent cannot consent on behalf of a new login. A duel never
        # resurrects/rewards either actor and is cancelled at character load.
        duel=self._services['duel']
        target=duel.get('target') if isinstance(duel,dict) else None
        self._lifecycle_cancelled_duel_target=target if isinstance(target,str) and 0<len(target)<=64 else ''
        self._services['duel']=None;self._combat_state.pop('duel',None)

    def _lifecycle_loaded_locked(self):
        target=getattr(self,'_lifecycle_cancelled_duel_target','')
        if target:
            for identity in ('player',target):
                actor=self._combat_state['actors'].get(identity)
                if actor:
                    actor['engaged_target']='';actor['statuses']=[e for e in actor.get('statuses',[]) if e['attacker_id'] not in ('player',target)]
        self._lifecycle_cancelled_duel_target=''

    def _lifecycle_position_locked(self):
        return dict(x=float(self._x[0]),y=float(self._y[0]),z=float(self._z[0]))

    def _lifecycle_move_locked(self,position):
        self._x[0],self._y[0],self._z[0]=(float(position[k]) for k in ('x','y','z'))
        self._vx[0]=self._vy[0]=self._vz[0]=0.
        self._legacy_held.clear();self._legacy_autorun=False;self._follow_id=''
        self._jump_held=False;self._grapple_anchor=None;self._grapple_projectile=None
        self._input.update(forward=0.,throttle=0.,strafe=0.,jump=False,grapple=False)
        self._movement_mode='GROUND';self._vehicle_kind='NONE';self._boat_entity_index=None
        self._input['movement_mode']='GROUND'
        self._jump_count=0;self._double_jump_pose_remaining_s=0.;self._stand_state=0
        self._grounded=True

    def _lifecycle_near_locked(self,identity):
        try:return self._service_person_locked(identity,nearby=True)==identity
        except ValueError:return False

    def _lifecycle_revive_locked(self,fraction,position=None):
        companion=(self._services.get('death') or {}).get('pet_number',0)
        actor=combat.ensure_actor(self._combat_state,'player',self._player_combat_profile_locked())
        actor.update(alive=True,health=max(1.,actor['max_health']*fraction),respawn_at=0.,engaged_target='',statuses=[],cooldown_until=0.)
        self._services['death']=None
        self._character_actions.pop('player',None)
        if position:self._lifecycle_move_locked(position)
        self._resume_companion_locked(companion)
        self._actions.auto_attack=False
        self._start_character_action_locked('player','Idle')
        from backend.game_engine_adapter_services import events
        return events('PLAYER_ALIVE')+events('PLAYER_UNGHOST')

    def _death_command_locked(self,row):
        from backend.game_engine_adapter_services import events
        op=row['op'];actor=combat.ensure_actor(self._combat_state,'player',self._player_combat_profile_locked())
        if op=='DeathEnter':
            if actor['alive'] or self._services['death']:return []
            now=self._service_now_locked()
            self._services['death']=dict(position=self._lifecycle_position_locked(),yaw=math.degrees(self._yaw[0]),serial=self._start_character_action_locked('player','Death'),
                ghost=False,release_at=now+360.,recover_at=now+30.,offer=None,healer='',pet_number=self._services['active_pet'])
            descriptor=self._instance_map_descriptor_locked()
            self._services['death'].update(map_id=descriptor['id'] if descriptor else 0,instance_id=descriptor['instance_id'] if descriptor else 0)
            if hasattr(self,'_cancel_spell_locked'):self._cancel_spell_locked('PLAYER_DEFEATED')
            self._actions.auto_attack=False
            for item in self._item_instances.values():
                if item.get('owner_id')=='player' and item.get('location')=='EQUIPPED' and item.get('kind') in ('WEAPON','ARMOR'):
                    item['condition']=max(0.,float(item.get('condition',1.))-.1)
            self._clear_local_ui_sessions_locked();self._services['duel']=None;self._combat_state.pop('duel',None)
            self._vx[0]=self._vy[0]=self._vz[0]=0.
            return events('PLAYER_DEAD')
        death=self._services['death']
        if actor['alive'] or not death:raise ValueError('DEATH_REQUIRED')
        now=self._service_now_locked()
        if op=='DeathRepop':
            if death['ghost']:raise ValueError('ALREADY_GHOST')
            death['ghost']=True;death['offer']=None
            self._suspend_companion_locked()
            self._character_actions.pop('player',None)
            bind=self._services['bind'];position=bind['position'] if bind else dict(x=0.,y=self._terrain_height_locked(0.,0.)+.65,z=0.)
            if self._instance_private_locked():
                place=self._expedition_places_locked()[self._expedition_record_locked()['ref']]
                x,z=place['x']+18.,place['z']
                position=dict(x=x,y=self._ground_contact_height_locked(x,z),z=z)
            self._lifecycle_move_locked(position)
            return events('PLAYER_ALIVE')+events('PLAYER_GHOST')
        if op=='DeathRetrieveCorpse':
            if not death['ghost']:raise ValueError('GHOST_REQUIRED')
            if now<death['recover_at']:raise ValueError('CORPSE_RECOVERY_DELAY')
            current=self._instance_map_descriptor_locked()
            if death.get('instance_id',0)!=(current['instance_id'] if current else 0):raise ValueError('CORPSE_IN_ANOTHER_MAP')
            if math.dist(tuple(self._lifecycle_position_locked().values()),tuple(death['position'][k] for k in ('x','y','z')))>5.:raise ValueError('CORPSE_OUT_OF_REACH')
            return self._lifecycle_revive_locked(.5)
        if op=='DeathOfferResurrect':
            identity=self._service_person_locked(row.get('target','target'),nearby=True)
            if identity=='player':raise ValueError('RESURRECT_OTHER_PERSON_REQUIRED')
            index=self._npc_index_for_id_locked(identity)
            death['offer']=dict(person=identity,expires=now+60.,position=dict(x=self._x[index],y=self._y[index],z=self._z[index]))
            return events('RESURRECT_REQUEST',self._service_unit_locked(identity)['name'])
        if op in ('DeathAcceptResurrect','DeathDeclineResurrect'):
            offer=death['offer']
            if not offer or offer['expires']<now:raise ValueError('RESURRECT_OFFER_EXPIRED')
            if op=='DeathDeclineResurrect':death['offer']=None;return []
            return self._lifecycle_revive_locked(.5,offer['position'])
        if op=='DeathHealerOpen':
            if not death['ghost']:raise ValueError('GHOST_REQUIRED')
            identity=self._service_person_locked(row.get('target','target'),nearby=True)
            if identity=='player':raise ValueError('SPIRIT_HEALER_REQUIRED')
            death['healer']=identity;return events('CONFIRM_XP_LOSS')
        if op=='DeathAcceptXpLoss':
            if not death['ghost'] or not self._lifecycle_near_locked(death['healer']):raise ValueError('SPIRIT_HEALER_OUT_OF_REACH')
            level=int(self._progression.get('level',1));minutes=min(10,max(0,level-9))
            self._services['sickness_until']=now+minutes*60
            for item in self._item_instances.values():
                if item.get('owner_id')=='player' and item.get('location') in ('EQUIPPED','INVENTORY') and item.get('kind') in ('WEAPON','ARMOR'):
                    item['condition']=max(0.,float(item.get('condition',1.))-.25)
            # XP is conserved: the dialog's historical name predates the
            # spirit-healer durability penalty.
            return self._lifecycle_revive_locked(1.)
        if op=='DeathUseSoulstone':
            item=next((i for i in self._item_instances.values() if i.get('owner_id')=='player' and i.get('location')=='INVENTORY'
                and (items.definition(self._item_catalog,i['definition_id']) or {}).get('self_resurrect') is True),None)
            if not item:raise ValueError('SELF_RESURRECT_ITEM_REQUIRED')
            if not self._consume_inventory_item_locked(item):raise ValueError('SELF_RESURRECT_CONSUME_FAILED')
            return self._lifecycle_revive_locked(.2,death['position'])
        raise ValueError('DEATH_COMMAND_UNKNOWN')

    def _bind_command_locked(self,row):
        from backend.game_engine_adapter_services import events
        if row['op']=='BinderOpen':
            identity=self._service_person_locked(row.get('target','target'),nearby=True)
            if identity=='player':raise ValueError('BINDER_OTHER_PERSON_REQUIRED')
            self._service_windows['binder']=identity;return events('CONFIRM_BINDER',self._service_unit_locked(identity)['name'])
        identity=self._service_windows.get('binder','')
        if not identity or not self._lifecycle_near_locked(identity):raise ValueError('BINDER_OUT_OF_REACH')
        if self._services['death']:raise ValueError('PLAYER_DEFEATED')
        index=self._npc_index_for_id_locked(identity)
        self._services['bind']=dict(person=identity,name=self._service_unit_locked(identity)['name'],position=dict(x=self._x[index],y=self._y[index],z=self._z[index]))
        self._service_windows['binder']=''
        return events('HEARTHSTONE_BOUND',self._services['bind']['name'])

    def _duel_command_locked(self,row):
        from backend.game_engine_adapter_services import events
        op=row['op'];duel=self._services['duel'];now=self._service_now_locked()
        if op in ('DuelStart','DuelRequest'):
            if duel or self._services['death']:raise ValueError('DUEL_UNAVAILABLE')
            identity=self._service_person_locked(row.get('target','target'),nearby=True)
            if identity=='player':raise ValueError('DUEL_OTHER_PERSON_REQUIRED')
            actor=combat.ensure_actor(self._combat_state,'player',self._player_combat_profile_locked())
            if actor.get('engaged_target'):raise ValueError('DUEL_OUT_OF_COMBAT_REQUIRED')
            index=self._npc_index_for_id_locked(identity);person=self._individual_state['individuals'][identity]
            other=combat.ensure_actor(self._combat_state,identity,self._npc_combat_profile_locked(identity,person))
            if not other['alive'] or other.get('engaged_target'):raise ValueError('DUEL_TARGET_UNAVAILABLE')
            self._services['duel']=dict(target=identity,state='REQUESTED' if op=='DuelRequest' else 'COUNTDOWN',deadline=now+(60 if op=='DuelRequest' else 3),origin=self._lifecycle_position_locked(),bounds_at=0.)
            if op=='DuelStart':self._combat_state['duel']=dict(participants=['player',identity],loser='',phase='COUNTDOWN')
            return events('DUEL_REQUESTED',self._service_unit_locked(identity)['name']) if op=='DuelRequest' else events('DUEL_COUNTDOWN',3000)
        if op=='DuelAccept':
            if not duel or duel['state']!='REQUESTED' or now>duel['deadline']:raise ValueError('DUEL_REQUEST_REQUIRED')
            if not self._lifecycle_near_locked(duel['target']):raise ValueError('DUEL_TARGET_OUT_OF_REACH')
            duel.update(state='COUNTDOWN',deadline=now+3.)
            self._combat_state['duel']=dict(participants=['player',duel['target']],loser='',phase='COUNTDOWN')
            return events('DUEL_COUNTDOWN',3000)
        if op=='DuelCancel':
            if not duel:raise ValueError('DUEL_REQUIRED')
            return self._duel_end_locked(duel['target'],'FORFEIT')
        raise ValueError('DUEL_COMMAND_UNKNOWN')

    def _duel_opponent_locked(self,identity):
        duel=self._services.get('duel')
        return bool(duel and duel['target']==identity and duel['state'] in ('COUNTDOWN','ACTIVE'))

    def _duel_end_locked(self,winner,reason):
        from backend.game_engine_adapter_services import events
        self._battlefield_duel_result_locked(winner,reason)
        duel=self._services['duel'];target=duel['target'] if duel else ''
        for identity in ('player',target):
            actor=self._combat_state['actors'].get(identity)
            if actor:
                actor['engaged_target']='';actor['statuses']=[e for e in actor.get('statuses',[]) if e['attacker_id'] not in ('player',target)]
        self._services['duel']=None;self._combat_state.pop('duel',None);self._actions.auto_attack=False
        self._append_event_locked('DUEL_FINISHED',reason,actor_id=winner)
        return events('DUEL_FINISHED')+events('DUEL_WINNER',self._service_unit_locked(winner)['name'],reason)

    def _tick_lifecycle_locked(self):
        actor=self._combat_state['actors'].get('player',{})
        if not actor.get('alive',True) and not self._services['death']:
            try:self._service_command_locked(dict(op='DeathEnter'))
            except (ValueError,OSError):pass # retain defeat and retry the durable transition.
        now=max(float(self._services['clock']),time.time());death=self._services['death']
        if death and not death['ghost'] and now>=death['release_at']:
            try:self._service_command_locked(dict(op='DeathRepop'))
            except (ValueError,OSError):pass
        duel=self._services['duel']
        if not duel:return
        if duel['state']=='REQUESTED' and now>=duel['deadline']:self._duel_end_locked('player','EXPIRED');return
        if duel['state']=='COUNTDOWN' and now>=duel['deadline']:
            duel['state']='ACTIVE';self._combat_state['duel']=dict(participants=['player',duel['target']],loser='',phase='ACTIVE')
        if duel['state']!='ACTIVE':return
        bound=math.dist(tuple(self._lifecycle_position_locked().values()),tuple(duel['origin'][k] for k in ('x','y','z')))>40.
        if bound and not duel['bounds_at']:duel['bounds_at']=now+10.
        if not bound:duel['bounds_at']=0.
        loser=self._combat_state.get('duel',{}).get('loser')
        if loser:self._duel_end_locked(duel['target'] if loser=='player' else 'player','VICTORY')
        elif duel['bounds_at'] and now>=duel['bounds_at']:self._duel_end_locked(duel['target'],'OUT_OF_BOUNDS')

    def _lifecycle_view_locked(self):
        now=max(float(self._services['clock']),time.time());death=self._services['death'];duel=self._services['duel']
        if not death:return dict(dead=False,ghost=False,bind=copy.deepcopy(self._services['bind']),binder_pending=self._lifecycle_near_locked(self._service_windows.get('binder','')),
            sickness_remaining=max(0.,self._services['sickness_until']-now),duel=copy.deepcopy(duel))
        return dict(dead=True,ghost=death['ghost'],position=copy.deepcopy(death['position']),release_remaining=max(0.,death['release_at']-now),
            map_id=death.get('map_id',0),instance_id=death.get('instance_id',0),
            recovery_delay=max(0.,death['recover_at']-now),healer_in_range=self._lifecycle_near_locked(death['healer']),
            sickness_duration=str(min(10,max(0,int(self._progression.get('level',1))-9))) if self._progression.get('level',1)>=10 else None,
            has_timer=False,has_sickness=False,resurrection_pending=bool(death['offer'] and death['offer']['expires']>now),
            self_res_label=next((i['name'] for i in self._item_instances.values() if i.get('owner_id')=='player' and i.get('location')=='INVENTORY' and (items.definition(self._item_catalog,i['definition_id']) or {}).get('self_resurrect') is True),None),
            bind=copy.deepcopy(self._services['bind']),binder_pending=False,duel=None)

    def _append_corpse_render_locked(self,rows,limit):
        death=self._services.get('death')
        if not death or not death['ghost'] or len(rows)>=limit:return
        current=self._instance_map_descriptor_locked()
        if death.get('instance_id',0)!=(current['instance_id'] if current else 0):return
        player=next((r for r in rows if r['id']=='e-0000'),None)
        if not player:return
        from backend import game_engine_assets as assets, game_engine_character_creation as appearance
        corpse=copy.deepcopy(player);corpse.update(id='corpse-player',kind='ACTOR',cast='CORPSE',speed=0.,vehicle='NONE',hidden=False,
            map_id=death.get('map_id',0),instance_id=death.get('instance_id',0),
            yaw=float(death.get('yaw',0.)),pitch=0.,roll=0.,motion_state='IDLE',**death['position'])
        corpse['animation'].update(action='Death',action_serial=max(1,int(death.get('serial',1))),cadence_hz=0.,locomotion='IDLE',state='IDLE')
        asset=assets.entity_binding(self._asset_catalog,'IDLE',0.,0,clip_override='Death')
        corpse['asset']=appearance.binding(self._character_creation,asset,'IDLE','Death')
        rows.append(corpse)
