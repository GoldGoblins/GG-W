"""Original camera/input intents over the local GG rig and character save.

The original VM owns binding gates. This adapter owns the five camera poses,
uses the reference's pitch/yaw conventions, and merges held Lua bindings with
physical input at the fixed step. Remote viewers and vehicle rigs stay separate.
"""
import copy,json,math

DEFAULT_VIEWS=((0.,0.,0.),(5.55,-10.,0.),(5.55,-20.,0.),(13.88,-30.,0.),(13.88,-10.,0.))
HELD=frozenset(('MoveForward','MoveBackward','TurnLeft','TurnRight','StrafeLeft','StrafeRight','TurnOrAction','CameraOrSelectOrMove'))

def number(value,lo,hi):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):raise ValueError('Ogiltigt kameravärde.')
    return max(lo,min(hi,float(value)))
def wrap(value):return (value+180.)%360.-180.

class ClientControlsMixin:
    def _reset_client_controls_locked(self):
        revision=getattr(self,'_camera_view_revision',-1)+1
        self._camera_view_revision=revision;self._camera_views=[list(v) for v in DEFAULT_VIEWS];self._camera_view_index=1
        self._camera_yaw_offset=0.;self._legacy_held=set();self._legacy_walk=False;self._legacy_autorun=False;self._legacy_jump=False
        self._player_display={'helm':True,'cloak':True,'sheath':1}
        self._stand_state=0;self._follow_id='';self._last_target_id='';self._last_enemy_id=''
        self._reset_local_client_locked()
        self._reset_services_locked()

    def _camera_pose_locked(self):
        return [self._camera_distance,self._camera_pitch,wrap(self._camera_yaw-math.degrees(self._yaw[0])-180.)]

    def _apply_camera_view_locked(self,pose):
        distance,pitch,yaw=pose
        self._camera_distance=number(distance,0,50);self._camera_pitch=number(pitch,-89,89);self._camera_yaw_offset=wrap(number(yaw,-1e9,1e9))
        self._camera_yaw=wrap(math.degrees(self._yaw[0])+self._camera_yaw_offset+180.)
        self._input.update(camera_distance=self._camera_distance,camera_pitch=self._camera_pitch,camera_yaw=self._camera_yaw)
        self._camera_view_revision+=1

    def _client_controls_save_locked(self):
        return {'views':copy.deepcopy(self._camera_views),'current':self._camera_view_index,
            'pose':list(self._opening_cinematic['restore']) if self._opening_cinematic else self._camera_pose_locked(),'display':dict(self._player_display),'local_client':copy.deepcopy(self._local_client),
            'services':copy.deepcopy(self._services),'survival':self._survival_save_locked()}

    def _restore_client_controls_locked(self,value):
        # Old saves have no camera section. Clear held channels on every load,
        # including character switches; no key or autorun survives logout.
        self._reset_client_controls_locked()
        self._restore_survival_locked(value.get('survival') if isinstance(value,dict) else None)
        if isinstance(value,dict):
            from backend.game_engine_adapter_local_client import restored
            self._local_client=restored(value.get('local_client'))
            self._restore_services_locked(value.get('services'))
        if not isinstance(value,dict):
            self._apply_camera_view_locked((self._camera_distance,self._camera_pitch,0.));return
        try:
            rows=value['views'];index=value['current'];pose=value['pose'];display=value.get('display',{})
            if not isinstance(rows,list) or len(rows)!=5 or type(index) is not int or not 0<=index<5:raise ValueError('Ogiltiga kameravyer.')
            def checked(row):
                if not isinstance(row,(list,tuple)) or len(row)!=3:raise ValueError('Ogiltig kameraposition.')
                return [number(row[0],0,50),number(row[1],-89,89),wrap(number(row[2],-1e9,1e9))]
            rows=[checked(row) for row in rows];pose=checked(pose)
            if not isinstance(display,dict) or any(type(display.get(k,True)) is not bool for k in ('helm','cloak')):raise ValueError('Ogiltigt utrustningsläge.')
            sheath=display.get('sheath',1)
            if type(sheath) is not int or not 0<=sheath<=2:raise ValueError('Ogiltigt vapenläge.')
        except (KeyError,TypeError,ValueError):
            self._apply_camera_view_locked((self._camera_distance,self._camera_pitch,0.));return
        self._camera_views=rows;self._camera_view_index=index;self._player_display={'helm':display.get('helm',True),'cloak':display.get('cloak',True),'sheath':sheath}
        self._apply_camera_view_locked(pose)

    def _client_controls_view_locked(self):
        from backend.game_engine_adapter_feedback import view
        from backend.game_engine_adapter_world_state import view as mounted_world_view
        return {'revision':self._camera_view_revision,'current':self._camera_view_index,'distance':self._camera_distance,
            'pitch':self._camera_pitch,'yaw':self._camera_yaw_offset,'views':copy.deepcopy(self._camera_views),
            'display':dict(self._player_display),'walk':self._legacy_walk,'autorun':self._legacy_autorun,
            'stand_state':self._stand_state,'following':self._follow_id,'local_client':self._local_client_view_locked(),
            'services':self._services_view_locked(),'spells':self._spells_view_locked(),'survival':self._survival_view_locked(),
            'world_feedback':view(self),'mounted_world':mounted_world_view(self)}

    def _stand_locked(self,state):
        if type(state) is not int or state not in (0,1,2,3,8):raise ValueError('Ogiltig kroppsställning.')
        self._ensure_combat_actors_locked()
        actor=self._combat_state.get('actors',{}).get('player',{})
        moving=any(abs(float(self._input.get(k,0)))>.01 for k in ('forward','throttle','strafe','turn','steer')) or bool(self._legacy_held&{'MoveForward','MoveBackward','StrafeLeft','StrafeRight','TurnLeft','TurnRight'}) or self._legacy_autorun
        # Original posture setter refuses dead/swimming/translating players.
        if not actor.get('alive',True) or (state and (moving or self._movement_mode!='GROUND' or self._vehicle_kind!='NONE')):return
        self._stand_state=state
        if state not in (0,2):
            self._player_display['sheath']=0;self._actions.auto_attack=False
            self._engine_loot={}
        self._render_snapshot_cache=None

    def _legacy_units_locked(self):
        self._ensure_combat_actors_locked()
        rows=self._target_rows_locked(require_sight=True)
        for row in rows:
            row['is_player']=False;row['party']=row['id'] in self._services['group']['members'];row['raid']=row['party'] and self._services['group']['raid']
            row['friend']=row['party'];row['can_attack']=not row['party']
        return rows

    def _legacy_unit_locked(self,token,*,by_name=False,exact=True):
        if not isinstance(token,str) or len(token)>128:raise ValueError('Ogiltigt mål.')
        if not by_name:
            if token.casefold()=='player':return 'player'
            if token.casefold()=='target':return self._combat_target_id
            if token.casefold().startswith(('party','raid')):
                try:return self._service_person_locked(token)
                except ValueError:return ''
            if token.casefold()=='targettarget':
                return str(self._combat_state.get('actors',{}).get(self._combat_target_id,{}).get('engaged_target',''))
        rows=self._legacy_units_locked()
        if by_name:
            name=token.casefold();return next((r['id'] for r in rows if r['name'].casefold()==name or (not exact and name in r['name'].casefold())),'') if name else ''
        return next((r['id'] for r in rows if token in (r['id'],r['entity_id'])),'')

    def _legacy_select_locked(self,identity):
        if identity==self._combat_target_id:return
        self._last_target_id=self._combat_target_id;self._combat_target_id=identity
        if identity and identity!='player':self._last_enemy_id=identity

    def _legacy_player_command_locked(self,row):
        op=row.get('op')
        if op=='Stand':self._stand_locked(row.get('state'))
        elif op=='Select':self._legacy_select_locked(self._legacy_unit_locked(row.get('unit','')))
        elif op=='ByName':self._legacy_select_locked(self._legacy_unit_locked(row.get('name',''),by_name=True,exact=bool(row.get('exact',True))))
        elif op=='Clear':self._legacy_select_locked('')
        elif op in ('LastTarget','LastEnemy'):
            old=self._last_target_id if op=='LastTarget' else self._last_enemy_id
            self._legacy_select_locked(self._legacy_unit_locked(old))
        elif op in ('Assist','AssistByName'):
            identity=self._legacy_unit_locked(row.get('unit',row.get('name','')),by_name=op=='AssistByName')
            target=self._combat_target_id if identity=='player' else self._combat_state.get('actors',{}).get(identity,{}).get('engaged_target','')
            if target:self._legacy_select_locked(self._legacy_unit_locked(target))
        elif op=='Nearest':
            mode=row.get('mode')
            if mode not in ('Enemy','Friend','PartyMember','RaidMember'):raise ValueError('Ogiltig måltyp.')
            predicate='can_attack' if mode=='Enemy' else {'Friend':'friend','PartyMember':'party','RaidMember':'raid'}[mode]
            rows=[r for r in self._legacy_units_locked() if r[predicate]]
            ids=[r['id'] for r in rows]
            identity=ids[(ids.index(self._combat_target_id)+(-1 if row.get('reverse') else 1))%len(ids)] if self._combat_target_id in ids else (ids[-1 if row.get('reverse') else 0] if ids else '')
            self._legacy_select_locked(identity)
        elif op in ('Follow','FollowByName'):
            identity=self._legacy_unit_locked(row.get('unit',row.get('name','')),by_name=op=='FollowByName',exact=bool(row.get('exact',True)))
            if identity and identity!='player':self._follow_id=identity
        elif op=='StopFollow':self._follow_id=''
        elif op=='Respec':
            self._ensure_combat_actors_locked()
            if not self._combat_state['actors']['player'].get('alive',True):raise ValueError('Karaktären måste vara vid liv.')
            ranks=self._progression.get('talents',{})
            if not isinstance(ranks,dict) or any(type(v) is not int or v<0 for v in ranks.values()):raise ValueError('Ogiltiga talangpoäng.')
            refund=sum(ranks.values());self._progression['talent_points']=int(self._progression.get('talent_points',0))+refund
            self._progression['talents']={key:0 for key in ranks}
            self._append_event_locked('TALENT_RESET',f'{refund} talent points returned.')
        else:raise ValueError('Okänt spelarkommando.')

    def _client_tick_input_locked(self,physical):
        row=self._legacy_input_locked(physical)
        if self._opening_cinematic:
            row.update(forward=0.,throttle=0.,strafe=0.,turn=0.,steer=0.,vertical=0.,jump=False,grapple=False,boost=False,
                       ability_1=False,ability_2=False,ability_3=False)
            return row
        if self._services.get('taxi_flight'):row.update(forward=0.,throttle=0.,strafe=0.,turn=0.,steer=0.,vertical=0.,jump=False,grapple=False,boost=False)
        if not self._combat_state.get('actors',{}).get('player',{}).get('alive',True):
            if self._is_ghost_locked():row.update(grapple=False,boost=False)
            else:row.update(forward=0.,throttle=0.,strafe=0.,turn=0.,steer=0.,jump=False,grapple=False,boost=False)
        moving=any(abs(float(row.get(k,0)))>.01 for k in ('forward','throttle','strafe'))
        keyboard_turn=abs(float(row.get('turn',row.get('steer',0))))>.01 and not row.get('mouse_look') and 'TurnOrAction' not in self._legacy_held
        if moving or keyboard_turn or row.get('jump'):self._stand_state=0
        if self._stand_state and self._movement_mode=='GROUND' and self._vehicle_kind=='NONE':
            row.update(forward=0.,throttle=0.,strafe=0.,boost=False)
        if self._follow_id and not self._replaying:
            # Follow survives arrival/range loss and jump. Manual translation
            # or keyboard turns cancel; orbiting the camera does not.
            if moving or keyboard_turn:self._follow_id=''
            else:
                target=next((r for r in self._target_rows_locked(only_id=self._follow_id) if r['id']==self._follow_id),None)
                if target:
                    dx,dz=target['x']-self._x[0],target['z']-self._z[0]
                    if math.hypot(dx,dz)>2.:
                        self._yaw[0]=math.atan2(dx,dz);row['forward']=row['throttle']=.5 if self._legacy_walk else 1.;self._stand_state=0
        return row

    def _legacy_input_locked(self,physical):
        if self._replaying:return dict(physical)
        row=dict(physical);held=self._legacy_held
        forward=int('MoveForward' in held)-int('MoveBackward' in held)
        if held&{'MoveForward','MoveBackward'}:row['forward']=row['throttle']=float(forward)
        elif self._legacy_autorun:row['forward']=row['throttle']=1.
        turn=int('TurnRight' in held)-int('TurnLeft' in held)
        strafe=int('StrafeRight' in held)-int('StrafeLeft' in held)
        if 'TurnOrAction' in held or row.get('mouse_look'):
            strafe+=turn;turn=0
        if held&{'TurnRight','TurnLeft'}:row['turn']=row['steer']=float(turn)
        if held&{'StrafeRight','StrafeLeft'} or strafe:row['strafe']=max(-1.,min(1.,float(strafe)))
        if self._legacy_walk:
            for key in ('forward','throttle','strafe'):row[key]=float(row.get(key,0))*.5
            row['boost']=False
        if self._legacy_jump:row['jump']=True;self._legacy_jump=False
        return row

    def _equipment_visual_locked(self,row):
        """GG authored item sockets use the same committed draw/stow state.

        Original M2 joints/template sheath types use the native selector. GG
        GLBs use their own back socket/rest; these are GG art placements.
        """
        row=self._tabard_equipment_visual_locked(row)
        slot=row.get('equipped_slot');state=self._player_display['sheath']
        if slot=='RANGED':return dict(row,visual_visible=state==2,visual_stowed=False)
        if slot not in ('MAIN_HAND','OFF_HAND'):return row
        if state==1:return dict(row,visual_stowed=False,visual_visible=True)
        rest=[-.18 if slot=='MAIN_HAND' else .18,.3,-.26]
        attachment=dict(row.get('attachment') or {},socket='BACK',node='SOCKET_BACK',rest=rest)
        return dict(row,attachment=attachment,visual_stowed=True,visual_visible=True)

    def client_controls_batch(self,raw):
        with self._lock:
            try:
                if not isinstance(raw,str) or len(raw)>16384:raise ValueError('För många styrkommandon.')
                rows=json.loads(raw)
                if not isinstance(rows,list) or len(rows)>128 or any(not isinstance(r,dict) for r in rows):raise ValueError('Ogiltiga styrkommandon.')
            except (ValueError,TypeError) as exc:
                self._legacy_held.clear();self._legacy_autorun=False;self._legacy_jump=False
                result=self.snapshot_locked();result['error']=str(exc);return result
            errors=[];events=[]
            for row in rows:
                result=self.client_control(json.dumps(row),_snapshot=False)
                if result.get('error'):errors.append(result['error'])
                events.extend(result.get('client_events',[]))
            result=self.snapshot_locked()
            if errors:result['client_control_errors']=errors[:8];result['error']=errors[0]
            if events:result['client_events']=events[:128]
            return result

    def client_control(self,raw,*,_snapshot=True):
        with self._lock:
            try:
                if not isinstance(raw,str) or len(raw)>32768:raise ValueError('För stort styrkommando.')
                row=json.loads(raw)
                if not isinstance(row,dict):raise ValueError('Ogiltigt styrkommando.')
                kind=row.get('kind');op=row.get('op');events=[]
                if kind=='local' and op=='Addon' and len(raw)>16384:
                    raise ValueError('För stort styrkommando.')
                if kind!='service' and not (kind=='local' and row.get('op')=='Addon') and len(raw)>2048:
                    raise ValueError('För stort styrkommando.')
                if kind=='local':events=self._local_client_command_locked(row)
                elif kind=='service':events=self._service_command_locked(row)
                elif kind=='spell':self._spell_control_locked(row)
                elif kind=='player':self._legacy_player_command_locked(row)
                elif kind=='camera':
                    if self._opening_cinematic:raise ValueError('CINEMATIC_IN_PROGRESS')
                    if op in ('Set','Save','Reset'):
                        index=row.get('index')
                        if type(index) is not int or not 0<=index<5:raise ValueError('Ogiltig kameravy.')
                    if op=='Set':self._camera_view_index=index;self._apply_camera_view_locked(self._camera_views[index])
                    elif op=='Save':self._camera_views[index]=self._camera_pose_locked()
                    elif op=='Reset':
                        self._camera_views[index]=list(DEFAULT_VIEWS[index])
                        if index==self._camera_view_index:self._apply_camera_view_locked(self._camera_views[index])
                    elif op in ('Next','Prev'):
                        index=max(0,min(4,self._camera_view_index+(1 if op=='Next' else -1)))
                        if index!=self._camera_view_index:self._camera_view_index=index;self._apply_camera_view_locked(self._camera_views[index])
                    elif op=='FlipYaw':
                        pose=self._camera_pose_locked();pose[2]=wrap(pose[2]+number(row.get('value'),-1e9,1e9));self._apply_camera_view_locked(pose)
                    else:raise ValueError('Okänt kamerakommando.')
                elif kind=='worn' and op in ('Helm','Cloak'):
                    key=op.lower();self._player_display[key]=not self._player_display[key]
                elif kind=='input' and op in ('Start','Stop'):
                    if self._opening_cinematic and op=='Start':raise ValueError('CINEMATIC_IN_PROGRESS')
                    key=row.get('key')
                    if key not in HELD:raise ValueError('Okänd rörelsekanal.')
                    if op=='Start':self._legacy_held.add(key)
                    else:self._legacy_held.discard(key)
                elif kind=='input' and op=='Cancel':
                    self._legacy_held.clear();self._legacy_autorun=False;self._legacy_jump=False
                elif kind=='input' and op=='Fire':
                    if self._opening_cinematic:raise ValueError('CINEMATIC_IN_PROGRESS')
                    key=row.get('key')
                    if key in ('CameraZoomIn','CameraZoomOut'):
                        delta=number(row.get('value'),0,50);pose=self._camera_pose_locked();pose[0]=max(0,min(50,pose[0]+(-delta if key=='CameraZoomIn' else delta)));self._apply_camera_view_locked(pose)
                    elif key=='Jump':self._legacy_jump=True;self._stand_state=0
                    elif key=='SitOrStand':self._stand_locked(1 if self._stand_state==0 else 0)
                    elif key=='ToggleRun':self._legacy_walk=not self._legacy_walk
                    elif key=='ToggleAutoRun':self._legacy_autorun=not self._legacy_autorun
                    elif key=='ToggleSheath':
                        if self._stand_state or self._vehicle_kind!='NONE' or not self._combat_state.get('actors',{}).get('player',{}).get('alive',True):return self.snapshot_locked() if _snapshot else {}
                        slots={i.get('equipped_slot') for i in self._item_instances.values() if i.get('location')=='EQUIPPED' and i.get('owner_id')=='player'}
                        melee=bool(slots&{'MAIN_HAND','OFF_HAND'});ranged='RANGED' in slots;current=self._player_display['sheath']
                        following=1 if current==0 and melee else 2 if current in (0,1) and ranged else 0 if current in (1,2) else current
                        self._player_display['sheath']=following;self._render_snapshot_cache=None
                    else:raise ValueError('Det här rörelsekommandot saknar ännu lokal spelkoppling.')
                else:raise ValueError('Okänt styrkommando.')
            except (ValueError,TypeError,json.JSONDecodeError) as exc:
                result=self.snapshot_locked() if _snapshot else {};result['error']=str(exc);return result
            result=self.snapshot_locked() if _snapshot else {}
            if events:result['client_events']=events
            return result
