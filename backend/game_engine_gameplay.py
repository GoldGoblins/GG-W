"""Shared GgEngine-style input, targeting and action-bar integration.

Rules adapted from samwhosung/engine under MIT; see licenses/engine-MIT.txt.
World picks name stable simulation identities. All effects validate distance,
ownership, health and cooldown again in the authoritative runtime.
"""
from __future__ import annotations
import copy,json,math
from backend import game_engine_actions as bars,game_engine_nature_catalog as nature
from backend import game_engine_items as items,game_engine_combat as combat
from backend import game_engine_npc as npc,game_engine_factions as factions
from backend import game_engine_economy as economy
from backend import game_engine_quests as quests,game_engine_dialogue as dialogue
from backend.game_engine_adapter_merchant import MerchantBundlesMixin

class GameplayMixin(MerchantBundlesMixin):
    def _vendor_durable_locked(self,action):
        """One checkpoint includes item custody, both wallets and buyback claims."""
        if getattr(self,'_service_atomic_active',False):return action()
        fields=('_item_instances','_inventory','_economy_state','_individual_state',
                '_combat_state','_quest_state','_event_journal','_events',
                '_npc_interaction_count','_npc_last_interaction','_last_item_interaction',
                '_persistence_revision','_item_counter')
        backup={key:copy.deepcopy(getattr(self,key)) for key in fields}
        result=None;self._service_atomic_active=True
        try:
            result=action()
            if result.get('error'):raise ValueError(result['error'])
            if any(getattr(self,key)!=backup[key] for key in
                   ('_item_instances','_economy_state','_individual_state')):
                self.save_state(snapshot=False)
            return result
        except (ValueError,TypeError,KeyError,OverflowError,OSError) as error:
            for key,value in backup.items():setattr(self,key,value)
            self._loot_items=[self._item_instances[r['instance_id']] for r in self._loot_items if r['instance_id'] in self._item_instances]
            self._ui_snapshot_base=None;self._render_snapshot_cache=None
            code='VENDOR_SAVE_FAILED' if isinstance(error,OSError) else str(error)
            snapshot=self._local_action_error_locked(code)
            snapshot['economy_result']={**((result or {}).get('economy_result') or {}),'ok':False,'error':code}
            return snapshot
        finally:self._service_atomic_active=False

    def _quest_contact_locked(self,npc_id):
        active=self._dialogue_state.get('active',{})
        if not npc_id or active.get('npc_id')!=npc_id:return False
        if npc_id in self._world_population.people:return bool(self._regional_interaction_target_locked(npc_id))
        index,_,error=self._conversation_target_locked(npc_id)
        return index is not None and not error

    def _quest_dialog_view_locked(self):
        panel=getattr(self,'_engine_quest_panel',{})
        if not panel or not self._quest_contact_locked(panel.get('npc_id')):return {'open':False}
        definition=self._quest_catalog.get(panel.get('quest_id'))
        if not definition or definition.get('giver_id')!=panel.get('npc_id'):return {'open':False}
        progress=self._quest_state.get('active',{}).get(panel['quest_id'],{})
        rewards=[]
        for ref in definition.get('rewards',{}).get('items',[])[:16]:
            item=self._item_catalog['items'].get(ref)
            if item:rewards.append(dict(item,definition_id=ref,quantity=1))
        return dict(panel,open=True,completable=progress.get('status')=='READY',rewards=rewards)

    def quest_dialog_select(self,npc_id,quest_id):
        with self._lock:
            definition=self._quest_catalog.get(quest_id)
            if not self._quest_contact_locked(npc_id):return {'error':'QUEST_GIVER_OUT_OF_RANGE_OR_SESSION_CLOSED'}
            if not definition or definition.get('giver_id')!=npc_id:return {'error':'QUEST_GIVER_MISMATCH'}
            active=quest_id in self._quest_state.get('active',{})
            if not active and quest_id not in quests.view(self._quest_state,self._quest_catalog)['available']:return {'error':'QUEST_UNAVAILABLE'}
            self._engine_quest_panel={'npc_id':npc_id,'quest_id':quest_id,'panel':'PROGRESS' if active else 'DETAIL'}
            self._engine_gossip_hidden=True
            return self.snapshot_locked()

    def quest_dialog_action(self,npc_id,quest_id,panel,action,choice=0):
        with self._lock:
            current=self._quest_dialog_view_locked()
            if not current.get('open') or (npc_id,quest_id,panel)!=(current.get('npc_id'),current.get('quest_id'),current.get('panel')):return {'error':'QUEST_PANEL_CHANGED_OR_CLOSED'}
            if action=='ACCEPT' and panel=='DETAIL':
                result=self.accept_quest(quest_id)
                if result.get('error'):return result
            elif action=='CONTINUE' and panel=='PROGRESS':
                if not current['completable']:return {'error':'QUEST_NOT_READY'}
                self._engine_quest_panel=dict(self._engine_quest_panel,panel='REWARD');return self.snapshot_locked()
            elif action=='REWARD' and panel=='REWARD':
                if type(choice) is not int or choice!=0:return {'error':'QUEST_REWARD_CHOICE_INVALID'}
                result=self.claim_quest(quest_id)
                if result.get('error'):return result
            elif action not in ('DECLINE','CLOSE'):return {'error':'QUEST_ACTION_INVALID_FOR_PANEL'}
            self._engine_quest_panel={};self._engine_gossip_hidden=False
            if action=='CLOSE':return self.close_dialogue()
            return self.snapshot_locked()

    def gossip_close(self):
        with self._lock:
            self._engine_gossip_hidden=True
            if self._quest_dialog_view_locked().get('open'):return self.snapshot_locked()
            return self.close_dialogue()

    def abandon_quest(self,quest_id):
        with self._lock:
            if quest_id not in self._quest_state.get('active',{}):return {'error':'QUEST_NOT_ACTIVE'}
            self._quest_state['active'].pop(quest_id);self._quest_state['revision']=int(self._quest_state.get('revision',0))+1
            if getattr(self,'_engine_quest_panel',{}).get('quest_id')==quest_id:self._engine_quest_panel={};self._engine_gossip_hidden=False
            self._append_event_locked('QUEST_ABANDON','Player abandoned an active quest.',actor_id='player',subject_id=quest_id)
            return self.snapshot_locked()

    def open_merchant(self, vendor_id=''):
        """Open a real nearby vendor; inspecting its catalogue is not a session."""
        with self._lock:
            valid, target = self._vendor_target_locked(str(vendor_id or ''))
            if not valid:
                return {'error': target['error']}
            self._open_merchant_id = target['vendor_id']
            self._open_stash_container_id = ''
            return self.snapshot_locked()

    def close_merchant(self):
        with self._lock:
            self._open_merchant_id = ''
            return self.snapshot_locked()

    def _merchant_view_locked(self):
        identity = self._open_merchant_id
        if not identity:
            return {'open': False, 'vendor_id': '', 'name': ''}
        valid, target = self._vendor_target_locked(identity)
        if not valid:
            # Walking back does not reopen a dismissed or invalidated session.
            self._open_merchant_id = ''
            return {'open': False, 'vendor_id': '', 'name': ''}
        repair_targets,cost=self._merchant_repair_quote_locked()
        buybacks=[]
        for row in self._economy_state.get('buybacks',{}).get(identity,[])[:12]:
            item=self._item_instances.get(row['instance_id'])
            if item and item.get('location')=='POCKET' and item.get('owner_id')==target['npc_id']:
                buybacks.append({'price':row['price'],'item':items.instance_view(self._item_catalog,item,sim_time=self._sim_time)})
        return {'open': True, 'vendor_id': identity,
                'name': str(target['vendor'].get('name', identity)),
                'buybacks':buybacks,'can_repair':True,'repair_gold':cost,
                'repair_items':{r['instance_id']:self._merchant_repair_cost(r) for r in repair_targets}}

    def _merchant_transaction(self, action, vendor_id, instance_id):
        with self._lock:
            session = self._merchant_view_locked()
            if not session['open'] or session['vendor_id'] != str(vendor_id):
                return {'error': 'MERCHANT_SESSION_REQUIRED'}
            return self._vendor_transaction_locked(action, vendor_id, instance_id)

    def merchant_buy(self, vendor_id, instance_id):
        return self._merchant_transaction('BUY', vendor_id, instance_id)

    def merchant_sell(self, vendor_id, instance_id, quantity=0):
        with self._lock:
            return self._vendor_durable_locked(lambda:self._merchant_sell_locked(vendor_id,instance_id,quantity))

    def _merchant_sell_locked(self, vendor_id, instance_id, quantity=0):
        with self._lock:
            session=self._merchant_view_locked()
            if not session['open'] or session['vendor_id']!=str(vendor_id):return {'error':'MERCHANT_SESSION_REQUIRED'}
            source=self._item_instance_locked(instance_id)
            if source is None:return {'error':'VENDOR_PLAYER_INSTANCE_REQUIRED'}
            if source.get('owner_id')!='player' or source.get('location')!='INVENTORY':return {'error':'VENDOR_SELL_LOCATION_INVALID'}
            if source.get('bound_to') and source['bound_to']!=str(self._persistence_key):return {'error':'ITEM_BOUND_TO_ANOTHER_CHARACTER'}
            if type(quantity) is not int or not 0<=quantity<=int(source['quantity']):raise ValueError('VENDOR_QUANTITY_INVALID')
            if quantity and quantity<source['quantity']:
                if self._item_binding_locked(source):raise ValueError('ITEM_PENDING_CONFIRMATION')
                if len(self._item_instances)>=items.MAX_WORLD_INSTANCES:raise ValueError('ITEM_INSTANCE_CAPACITY')
                split=copy.deepcopy(source);split.update(instance_id=self._next_item_instance_id_locked('merchant-split'),quantity=quantity,slot_index=-1)
                source['quantity']-=quantity;instance_id=split['instance_id'];self._item_instances[instance_id]=split
            result=self._vendor_transaction_locked('SELL',vendor_id,instance_id,reserve_buyback=True)
            if result.get('error'):return result
            rows=self._economy_state.setdefault('buybacks',{}).setdefault(vendor_id,[])
            rows[:]=[r for r in rows if r['instance_id']!=instance_id]
            rows.append({'instance_id':instance_id,'price':result['economy_result']['total_price']});rows[:]=rows[-12:]
            self._sync_saved_player_items_locked()
            snapshot=self.snapshot_locked();snapshot['economy_result']=result['economy_result'];return snapshot

    def merchant_buy_at(self,vendor_id,instance_id,slot):
        with self._lock:
            session=self._merchant_view_locked()
            if not session['open'] or session['vendor_id']!=str(vendor_id):return {'error':'MERCHANT_SESSION_REQUIRED'}
            return self._vendor_transaction_locked('BUY',vendor_id,instance_id,destination_slot=slot)

    def merchant_buyback(self,vendor_id,instance_id):
        with self._lock:
            return self._vendor_durable_locked(lambda:self._merchant_buyback_locked(vendor_id,instance_id))

    def _merchant_buyback_locked(self,vendor_id,instance_id):
        with self._lock:
            session=self._merchant_view_locked()
            if not session['open'] or session['vendor_id']!=str(vendor_id):return {'error':'MERCHANT_SESSION_REQUIRED'}
            rows=self._economy_state.get('buybacks',{}).get(vendor_id,[])
            record=next((r for r in rows if r['instance_id']==instance_id),None)
            if record is None or not any(r['item']['instance_id']==instance_id for r in session['buybacks']):return {'error':'MERCHANT_BUYBACK_UNAVAILABLE'}
            result=self._vendor_transaction_locked('BUY',vendor_id,instance_id,buyback_price=record['price'])
            if result.get('error'):return result
            rows.remove(record);self._sync_saved_player_items_locked()
            snapshot=self.snapshot_locked();snapshot['economy_result']={**result['economy_result'],'action':'BUYBACK'};return snapshot

    def _merchant_repair_quote_locked(self,instance_id=''):
        targets=[];total=0
        for row in self._item_instances.values():
            if row.get('owner_id')!='player' or row.get('location') not in ('INVENTORY','EQUIPPED') or not isinstance(row.get('gear'),dict) or instance_id and row.get('instance_id')!=instance_id:continue
            condition=float(row.get('condition',1.))
            if not math.isfinite(condition) or condition>=1.:continue
            cost=self._merchant_repair_cost(row)
            targets.append(row);total+=cost
        return targets,total

    @staticmethod
    def _merchant_repair_cost(row):
        # GG content uses a condition fraction and whole gold. This is its
        # explicit local service price, rather than an invented DBC cost.
        level=max(1,min(60,int(row.get('level',1))))
        return math.ceil(max(0.,1.-float(row.get('condition',1.)))*level*10)

    def merchant_repair(self,vendor_id,instance_id=''):
        with self._lock:
            return self._vendor_durable_locked(lambda:self._merchant_repair_locked(vendor_id,instance_id))

    def _merchant_repair_locked(self,vendor_id,instance_id=''):
        with self._lock:
            session=self._merchant_view_locked()
            if not session['open'] or session['vendor_id']!=str(vendor_id):return {'error':'MERCHANT_SESSION_REQUIRED'}
            if instance_id and not any(r.get('instance_id')==instance_id and r.get('owner_id')=='player' and r.get('location') in ('INVENTORY','EQUIPPED') for r in self._item_instances.values()):return {'error':'MERCHANT_REPAIR_ITEM_INVALID'}
            targets,cost=self._merchant_repair_quote_locked(instance_id)
            wallet=self._economy_state['wallet'];account=self._economy_state['vendors'][vendor_id]
            if wallet['gold']<cost:return {'error':'PLAYER_GOLD_INSUFFICIENT'}
            if account['gold']>economy.MAX_CURRENCY-cost:return {'error':'VENDOR_GOLD_CAPACITY'}
            for row in targets:row['condition']=1.
            wallet['gold']-=cost;wallet['spent']=economy.bounded_currency(wallet.get('spent',0)+cost);wallet['revision']+=1
            account['gold']+=cost;account['revision']+=1
            self._append_event_locked('MERCHANT_REPAIR',f'Repaired {len(targets)} items for {cost} gold.')
            self._sync_saved_player_items_locked()
            snapshot=self.snapshot_locked();snapshot['economy_result']={'ok':True,'action':'REPAIR','total_price':cost,'items':len(targets)};return snapshot

    def close_bank(self):
        with self._lock:
            self._open_stash_container_id = ''
            return self.snapshot_locked()

    def _action_definitions_locked(self):
        if getattr(self,'_action_catalog_identity',None) is not self._item_catalog:
            self._action_catalog_identity=self._item_catalog
            self._action_definitions={k:v for group in ('materials','insertables','containers','items')
                                      for k,v in self._item_catalog.get(group,{}).items()}
        return self._action_definitions

    def _world_interaction_rows_locked(self):
        rows=[];people=self._individual_state.get('individuals',{});actors=self._combat_state.get('actors',{})
        for i in self._npc_indices:
            if not self._alive[i] or not self._npc_ids[i]:continue
            identity=self._npc_ids[i];actor=actors.get(identity,{})
            distance=math.sqrt((self._x[i]-self._x[0])**2+(self._y[i]-self._y[0])**2+(self._z[i]-self._z[0])**2)
            if distance>64:continue
            person=people.get(identity,{})
            rep=self._faction_state.get('people',{}).get(identity,{})
            hostile=rep.get('disposition')=='HOSTILE' or float(rep.get('standing',0))<=-50 or actor.get('engaged_target')=='player'
            dead=not actor.get('alive',True)
            vendor=any(v.get('npc_id')==identity for v in self._vendor_catalog.values())
            rows.append({'id':identity,'entity_id':f'e-{i:04d}','kind':'NPC','name':person.get('name') or 'Villager',
                         'x':self._x[i],'y':self._y[i],'z':self._z[i],'radius':.6,'distance_m':distance,
                         'health':actor.get('health',1),'max_health':actor.get('max_health',1),'dead':dead,
                         'attackable':hostile,'combat_with_me':actor.get('engaged_target')=='player',
                         'cursor':'LOOT' if dead else 'ATTACK' if hostile else 'SHOP' if vendor else 'TALK',
                         'in_range':distance<=(3.75 if dead else self._player_combat_profile_locked()['attack_range_m']+.35 if hostile else npc.INTERACTION_RADIUS_M)})
        for identity in self._world_population.active:
            person=self._world_population.people[identity]
            if not person['alive']:continue
            p=self._world_population.position(identity,self._sim_time)
            distance_xz=math.hypot(p['x']-self._x[0],p['z']-self._z[0])
            if distance_xz>64:continue
            y=self._terrain_height_locked(p['x'],p['z'])+.65
            distance=math.hypot(distance_xz,y-self._y[0])
            rows.append(dict(id=identity,entity_id=identity,kind='NPC',name=person['name'],
                x=p['x'],y=y,z=p['z'],radius=.6,distance_m=distance,health=person['health'],max_health=60,
                dead=False,attackable=False,cursor='TALK',in_range=distance<=npc.INTERACTION_RADIUS_M))
        for r in self._nature.rows:
            s=nature.SPECIES[r['species']];state=self._nature.states.get(r['id'],{});dead=bool(state.get('dead'))
            distance=math.sqrt((r['x']-self._x[0])**2+(r['y']+.2-self._y[0])**2+(r['z']-self._z[0])**2)
            if distance>64:continue
            plant=s['domain']=='PLANT';action=next((a for a,v in s['actions'].items() if v['resource'] and bool(v.get('dead'))==dead),'PET')
            rows.append({'id':r['id'],'kind':'NATURE','species':s['id'],'name':s['name'],'x':r['x'],'y':r['y'],'z':r['z'],
                         'radius':max(.12,s['size']*.5),'distance_m':distance,'dead':dead,'health':state.get('health',s['health']),
                         'max_health':s['health'],'attackable':not plant,'no_tab':plant or s['size']<.6,
                         'cursor':'LOOT' if dead else 'HERB' if plant else 'FISH' if action=='FISH' else 'CATCH' if action=='CATCH' else 'SHEAR' if action=='SHEAR' else 'MILK' if action=='MILK' else 'PET',
                         'in_range':distance<=(8 if action in {'CATCH','FISH'} else 3.75)})
        for identity,r in self._item_instances.items():
            if r.get('location')!='GROUND' or not self._instance_item_visible_locked(r):continue
            p=r.get('position',{});x=float(p.get('x',0));y=float(p.get('y',0));z=float(p.get('z',0))
            distance=math.sqrt((x-self._x[0])**2+(y-self._y[0])**2+(z-self._z[0])**2)
            if distance>64:continue
            definition=self._action_definitions_locked().get(r.get('definition_id'),{})
            rows.append({'id':identity,'entity_id':'item-'+identity,'kind':'ITEM','name':definition.get('name','Item'),'x':x,'y':y,'z':z,'radius':.45,
                         'distance_m':distance,'attackable':False,'cursor':'OPEN' if definition.get('kind')=='CONTAINER' else 'LOOT','in_range':distance<=items.INTERACTION_RADIUS_M})
        return rows[:256]

    def _selected_interaction_locked(self):
        if not self._combat_target_id:return {}
        return next((r for r in self._world_interaction_rows_locked() if r['id']==self._combat_target_id),{})

    def world_select(self,identity):
        with self._lock:
            rows=self._world_interaction_rows_locked();wanted=str(identity or '')
            if wanted and not any(r['id']==wanted for r in rows):return {'error':'TARGET_NOT_RESIDENT'}
            self._combat_target_id=wanted;self._actions.auto_attack=False
            return self.render_snapshot_locked()

    def world_hover(self,identity):
        with self._lock:
            row=next((r for r in self._world_interaction_rows_locked() if r['id']==identity),{})
            if row.get('kind')=='NATURE':
                target=self._nature.target(self._x[0],self._y[0],self._z[0],self._sim_time,self._inventory,identity)
                ready=next((a for a in target.get('actions',[]) if a['id'] not in {'PET','ATTACK'} and a['ready']),None)
                if ready:
                    cursor={'SKIN':'SKIN','LOOT':'LOOT','FISH':'FISH','CATCH':'CATCH','SHEAR':'SHEAR','MILK':'MILK','BRUSH':'BRUSH','PICK':'HERB','CLIP':'HERB'}.get(ready['id'],row['cursor'])
                    row={**row,'in_range':True,'action':ready['id'],'cursor':cursor}
                elif target.get('actions'):row={**row,'in_range':False,'reason':next((a['reason'] for a in target['actions'] if a['id'] not in {'PET','ATTACK'}),'Move closer')}
            return row

    def world_context(self,identity=''):
        with self._lock:
            wanted=str(identity or self._combat_target_id or '')
            if not wanted:
                rows=self._world_interaction_rows_locked();row=min((r for r in rows if r['in_range']),key=lambda r:r['distance_m'],default={})
            else:row=next((r for r in self._world_interaction_rows_locked() if r['id']==wanted),{})
            if not row:return {'error':'INTERACTION_TARGET_REQUIRED'}
            if row['kind']=='NATURE':return self.nature_action(row['id'],'')
            if row['kind']=='ITEM':return self.open_container(row['id']) if row['cursor']=='OPEN' else self.pickup_item(row['id'])
            if row.get('dead'):return {'error':'REMAINS_ALREADY_EMPTY'}
            if row['attackable']:
                self._combat_target_id=row['id'];self._actions.auto_attack=True;return self.render_snapshot_locked()
            if row['id'] in self._world_population.people:return self.talk_npc(row['id'],'')
            if row['cursor']=='SHOP':
                vendor=next((key for key,value in self._vendor_catalog.items() if value.get('npc_id')==row['id']),None)
                if vendor:return self.open_merchant(vendor)
            index,distance,error=self._conversation_target_locked(row['id'])
            if error:return {'error':error}
            return self.talk_npc(row['id'],'')

    def world_target_cycle(self,raw='{}',reverse=False):
        with self._lock:
            self._ecology_view_locked()
            try:camera=json.loads(raw)
            except (ValueError,TypeError):camera={}
            rows=[r for r in self._world_interaction_rows_locked() if r.get('attackable') and not r.get('dead')]
            # Project the real camera's frustum, not the character's facing cone.
            try:
                heading=math.radians(float(camera.get('heading',math.degrees(self._yaw[0]))));pitch=math.radians(float(camera.get('pitch',-8)))
                aspect=max(.2,min(5,float(camera.get('aspect',1.6))));fov=max(20,min(100,float(camera.get('fov',45))))
                cx=float(camera.get('x',self._x[0]));cy=float(camera.get('y',self._y[0]));cz=float(camera.get('z',self._z[0]))
            except (TypeError,ValueError,OverflowError):return {'error':'TARGET_CAMERA_INVALID'}
            if not all(math.isfinite(v) for v in (heading,pitch,aspect,fov,cx,cy,cz)):return {'error':'TARGET_CAMERA_INVALID'}
            right=(-math.cos(heading),0,math.sin(heading));forward=(math.sin(heading)*math.cos(pitch),math.sin(pitch),math.cos(heading)*math.cos(pitch))
            up=(-math.sin(heading)*math.sin(pitch),math.cos(pitch),-math.cos(heading)*math.sin(pitch))
            for r in rows:
                delta=(r['x']-cx,r['y']+.5-cy,r['z']-cz);depth=sum(a*b for a,b in zip(delta,forward))
                sx=sum(a*b for a,b in zip(delta,right))/max(.01,depth*math.tan(math.radians(fov)*.5)*aspect)
                sy=sum(a*b for a,b in zip(delta,up))/max(.01,depth*math.tan(math.radians(fov)*.5))
                r.update(on_screen=depth>0 and abs(sx)<=.8 and abs(sy)<=.8,off_center=min(2,math.hypot(sx,sy)))
            self._combat_target_id=self._actions.cycle(rows,self._combat_target_id,self._sim_time,reverse)
            self._actions.auto_attack=False;return self.render_snapshot_locked()

    def _action_view_locked(self):
        bar=self._actions;selected=self._selected_interaction_locked();slots=[]
        definitions=self._action_definitions_locked();carried={};equipped=set();appearances={};tool_target=None
        availability={}
        def spell_availability(ref,ability):
            # Slots, macros and the ability catalogue observe the same locked
            # state here. This memo ends with this one view; casts never use it.
            if ref not in availability:availability[ref]=self._spell_availability_locked(ref,ability)
            return availability[ref]
        for instance in self._item_instances.values():
            if instance.get('owner_id')=='player' and instance.get('location') in {'INVENTORY','EQUIPPED'}:
                ref=instance.get('definition_id');carried[ref]=carried.get(ref,0)+int(instance.get('quantity',1))
                appearances.setdefault(ref,items.item_appearance_index(instance.get('instance_id','')))
                if instance.get('location')=='EQUIPPED':equipped.add(ref)
        for i,entry in enumerate(bar.slots):
            row={'index':i,'key':bars.KEYS[i%12],**entry,'name':'','count':0,'usable':False,'cooldown_s':0,'current':False,'in_range':True,'not_enough_resource':False}
            kind=entry.get('kind');ref=entry.get('ref');reason=''
            if kind=='ABILITY':
                ability=self._content.get('abilities',{}).get(ref,{})
                row.update(name=ability.get('name',ref),cooldown_s=self._ability_cooldowns.get(ref,0),cooldown_duration_s=ability.get('cooldown_s',1),not_enough_resource=self._resource<float(ability.get('resource_cost',0)))
                if not self._combat_state.get('actors',{}).get('player',{}).get('alive',True):
                    reason='Defeated'
                else:
                    reason='Not enough energy' if row['not_enough_resource'] else 'Cooldown' if row['cooldown_s'] else ''
            elif kind=='COMMAND':
                row['name']=bars.COMMANDS.get(ref,ref);row['current']=ref=='ATTACK' and bar.auto_attack
                if ref=='ATTACK':
                    row['in_range']=bool(selected.get('attackable')) and selected['distance_m']<=(3.75 if selected.get('kind')=='NATURE' else self._player_combat_profile_locked()['attack_range_m']+.35)
                    reason='Select a target' if not selected.get('attackable') else 'Out of range' if not row['in_range'] else ''
                elif ref=='INTERACT':reason='' if selected.get('in_range') or any(r['in_range'] for r in self._world_interaction_rows_locked()) else 'Move closer'
            elif kind=='MACRO':
                macro=getattr(self,'_client_macros',{}).get(str(ref))
                row['name']=macro['name'] if macro else 'Missing macro'
                if macro:
                    row['texture']=macro.get('texture')
                    ability=self._content.get('abilities',{}).get(macro.get('ability'))
                    if ability:
                        row.update(cooldown_s=self._ability_cooldowns.get(macro['ability'],0),cooldown_duration_s=ability.get('cooldown_s',1),not_enough_resource=self._resource<float(ability.get('resource_cost',0)))
                        reason='Defeated' if not self._combat_state.get('actors',{}).get('player',{}).get('alive',True) else 'Not enough energy' if row['not_enough_resource'] else 'Cooldown' if row['cooldown_s'] else ''
                    elif macro.get('unresolved'):reason='Unknown ability'
                else:reason='Missing macro'
            elif kind=='ITEM':
                definition=definitions.get(ref,{})
                quantity=carried.get(ref,0)
                from backend.game_engine_assets import inventory_icon
                row['texture']=inventory_icon(ref,appearances.get(ref,0))
                row.update(name=definition.get('name',ref),count=quantity,cooldown_s=max(0,self._action_item_cooldowns.get(ref,0)-self._sim_time),equipped=ref in equipped,current=ref in equipped)
                reason='Not in bag' if quantity==0 else 'Cooldown' if row['cooldown_s'] else ''
                if not reason and definition.get('kind')=='TOOL':
                    if tool_target is None:
                        tool_target=self._nature.target(self._x[0],self._y[0],self._z[0],self._sim_time,self._inventory,selected.get('id','') if selected.get('kind')=='NATURE' else '')
                    choices=[a for a in tool_target.get('actions',[]) if a.get('tool')==ref]
                    if choices:
                        row['cooldown_s']=max(a.get('cooldown_s',0) for a in choices)
                        row['cooldown_duration_s']=max(nature.SPECIES[tool_target['species']]['actions'][a['id']]['cooldown_s'] for a in choices)
                    reason=next((a['reason'] for a in choices if a['ready']),'No suitable target') if not any(a['ready'] for a in choices) else ''
                elif not reason and definition.get('kind')=='CONSUMABLE':
                    row['cooldown_duration_s']=2
                    actor=self._combat_state.get('actors',{}).get('player',{})
                    if 'RECOVERY' not in definition.get('tags',[]):reason='No use effect'
                    elif not actor.get('alive',True):reason='Defeated'
                    elif actor.get('health',0)>=actor.get('max_health',1) and self._resource>=100:reason='Already recovered'
                elif not reason and ref=='item.enchant_scroll':
                    from backend import game_engine_enchants as enchants
                    scroll=next((i for i in self._item_instances.values() if i.get('definition_id')==ref and i.get('owner_id')=='player' and i.get('location')=='INVENTORY'),None)
                    enchant=enchants.definition((scroll or {}).get('scroll_enchant_id',''))
                    reason='No use effect' if not enchant else 'Defeated' if self._player_defeated_locked() else 'Level required' if self._progression.get('level',1)<enchant['required_level'] else 'Pending confirmation' if self._item_binding_locked(scroll) else ''
                elif not reason and ref in ('item.gg_wrapping_paper','item.gg_wrapped_gift','item.gg_letter','item.guild_charter'):
                    reason='Defeated' if self._player_defeated_locked() else ''
                elif not reason and definition.get('kind') not in {'TOOL','CONSUMABLE','WEAPON','ARMOR','GEAR','EQUIPMENT'} and not definition.get('equip_slot'):reason='Crafting material'
            row['reason']=reason;row['usable']=bool(kind) and not reason
            if kind=='ABILITY':row.update(spell_availability(ref,self._content.get('abilities',{}).get(ref,{})))
            elif kind=='MACRO' and macro and macro.get('ability'):
                row.update(spell_availability(macro['ability'],self._content.get('abilities',{}).get(macro['ability'],{})))
            slots.append(row)
        return {'schema':bars.SCHEMA,'revision':bar.revision,'page':bar.page,'pages':bars.PAGES,'locked':bar.locked,'auto_attack':bar.auto_attack,'slots':slots,
                'abilities':[{'kind':'ABILITY','ability_kind':v.get('kind','MOVEMENT'),'ref':key,'name':v.get('name',key),
                    'resource_cost':v.get('resource_cost',0),'description':v.get('description',''),'icon':v.get('icon'),
                    'cast_time_s':v.get('cast_time_s',0),'channel_time_s':v.get('channel_time_s',0),'range_m':v.get('range_m',0),
                    'effect':v.get('effect',{}),'modes':v.get('tags',[]),
                    'cooldown_s':self._ability_cooldowns.get(key,0),'cooldown_duration_s':v.get('cooldown_s',1),
                    'not_enough_resource':self._resource<float(v.get('resource_cost',0)),
                    'usable':not self._ability_cooldowns.get(key,0) and self._resource>=float(v.get('resource_cost',0)) and self._combat_state.get('actors',{}).get('player',{}).get('alive',True),
                    **spell_availability(key,v)
                } for key,v in self._content.get('abilities',{}).items()]}

    def action_bar_edit(self,raw):
        with self._lock:
            try:p=json.loads(raw)
            except (ValueError,TypeError):return {'error':'ACTION_EDIT_INVALID'}
            if not isinstance(p,dict):return {'error':'ACTION_EDIT_INVALID'}
            verb=p.get('verb','ASSIGN')
            if verb=='PAGE':
                page=p.get('page',0);self._actions.page=max(0,min(bars.PAGES-1,page)) if type(page) is int else 0;result={'ok':True}
            elif verb=='LOCK':self._actions.locked=bool(p.get('locked'));result={'ok':True}
            elif verb=='MOVE':result=self._actions.move(p.get('source'),p.get('index'))
            else:result=self._actions.assign(p.get('index'),p.get('kind','EMPTY'),p.get('ref',''),self._content.get('abilities',{}),self._action_definitions_locked())
            self._actions.revision+=1
            snapshot=self.render_snapshot_locked();snapshot['action_result']=result
            if result.get('error'):snapshot['error']=result['error']
            return snapshot

    def set_client_macros(self,raw):
        """Bounded presentation metadata; macro bodies stay in the native UI VM."""
        try:
            rows=json.loads(raw)
            if not isinstance(rows,list) or len(rows)>36:raise ValueError('macro list')
            values={}
            for row in rows:
                index=row['index'];name=row['name'];texture=row.get('texture');ability=row.get('ability')
                if type(index) is not int or not 1<=index<=36 or str(index) in values or not isinstance(name,str) or len(name)>16 or texture is not None and (not isinstance(texture,str) or len(texture)>512):raise ValueError('macro metadata')
                if ability is not None and ability not in self._content.get('abilities',{}):raise ValueError('macro ability')
                values[str(index)]={'name':name,'texture':texture,'ability':ability,'unresolved':bool(row.get('unresolved'))}
        except (ValueError,TypeError,KeyError):return {'error':'MACRO_STATE_INVALID'}
        with self._lock:
            if getattr(self,'_client_macros',{})!=values:self._client_macros=values;self._actions.revision+=1
        return {'ok':True}

    def action_use(self,index):
        with self._lock:
            if not isinstance(index,int) or not 0<=index<len(self._actions.slots):return {'error':'ACTION_SLOT_INVALID'}
            entry=self._actions.slots[index];kind=entry.get('kind');ref=entry.get('ref')
            if kind=='ABILITY':return self.activate_ability(ref)
            if kind=='COMMAND':
                return self.action_command(ref)
            if kind=='ITEM':return self.action_use_item(ref)
            if kind=='MACRO':return {'error':'ACTION_MACRO_PRESENTATION_REQUIRED'}
            return {'error':'ACTION_SLOT_EMPTY'}

    def action_command(self,command):
        with self._lock:
            if self._services.get('taxi_flight'):return {'error':'TAXI_IN_PROGRESS'}
            if command=='ATTACK':
                selected=self._selected_interaction_locked()
                if not selected.get('attackable') or selected.get('dead'):return {'error':'COMBAT_TARGET_REQUIRED'}
                self._actions.auto_attack=not self._actions.auto_attack
                return self.render_snapshot_locked()
            if command=='INTERACT':return self.world_context()
            if command in bars.COMMANDS:return self.mobility_action(command)
            return {'error':'ACTION_REFERENCE_INVALID'}

    def action_use_item(self,definition_id,instance_id='',*,_bind_confirmed=False):
        with self._lock:
            if self._services.get('taxi_flight'):return {'error':'TAXI_IN_PROGRESS'}
            definition=self._action_definitions_locked().get(definition_id,{})
            instance=next((r for r in self._item_instances.values() if r.get('definition_id')==definition_id and (not instance_id or r.get('instance_id')==instance_id) and r.get('location')=='INVENTORY' and r.get('owner_id')=='player'),None)
            if not instance:
                if not instance_id and definition.get('equip_slot') and any(r.get('definition_id')==definition_id and r.get('location')=='EQUIPPED' and r.get('owner_id')=='player' for r in self._item_instances.values()):
                    return self.render_snapshot_locked()
                return {'error':'ITEM_NOT_IN_INVENTORY'}
            if self._action_item_cooldowns.get(definition_id,0)>self._sim_time:return {'error':'ITEM_ON_COOLDOWN'}
            if instance.get('scroll_enchant_id'):
                if not _bind_confirmed and self._item_binding_needed_locked(instance,'USE'):
                    self._ensure_inventory_slots_locked()
                    return self._item_binding_request_locked('ItemBindingUse',instance)
                try:events=self._service_command_locked({'op':'EnchantOpen','item':instance['instance_id']})
                except ValueError as exc:return {'error':str(exc)}
                result=self.snapshot_locked();result['client_events']=events;return result
            if definition_id=='item.gg_wrapped_gift' or 'GIFT_WRAPPER' in definition.get('tags',[]):
                self._ensure_inventory_slots_locked()
                op='InventoryUnwrap' if definition_id=='item.gg_wrapped_gift' else 'InventoryWrapOpen'
                try:events=self._service_command_locked({'op':op,'item':instance['instance_id']})
                except ValueError as exc:return {'error':str(exc)}
                result=self.snapshot_locked();result['client_events']=events;return result
            if definition_id == 'item.gg_letter':
                try:events=self._service_command_locked({'op':'ItemTextOpen','item':instance['instance_id']})
                except ValueError as error:return {'error':str(error)}
                result=self.snapshot_locked();result['client_events']=events;return result
            if definition.get('kind')=='TOOL':
                target=self._selected_interaction_locked();wanted=target.get('id','') if target.get('kind')=='NATURE' else ''
                target=self._nature.target(self._x[0],self._y[0],self._z[0],self._sim_time,self._inventory,wanted)
                action=next((a for a in target.get('actions',[]) if a.get('tool')==definition_id and a['ready']),None)
                if not action:return {'error':'ITEM_TOOL_TARGET_REQUIRED'}
                return self.nature_action(target['id'],action['id'])
            if definition.get('kind')=='CONSUMABLE':
                if 'RECOVERY' not in definition.get('tags',[]):return {'error':'ITEM_NO_USE_EFFECT'}
                actor=combat.ensure_actor(self._combat_state,'player',self._player_combat_profile_locked())
                if not actor.get('alive'):return {'error':'COMBAT_PLAYER_DEFEATED'}
                if actor['health']>=actor['max_health'] and self._resource>=100:return {'error':'ITEM_ALREADY_RECOVERED'}
                if not _bind_confirmed and self._item_binding_needed_locked(instance,'USE'):
                    self._ensure_inventory_slots_locked()
                    return self._item_binding_request_locked('ItemBindingUse',instance)
                if not self._consume_inventory_item_locked(instance):return {'error':'ITEM_CONSUME_FAILED'}
                actor['health']=min(actor['max_health'],actor['health']+25);self._resource=min(100,self._resource+25)
                self._action_item_cooldowns[definition_id]=self._sim_time+2
                self._append_event_locked('ITEM_USE',definition.get('name','Item')+' used.',actor_id='player')
                return self.snapshot_locked()
            if definition_id=='item.guild_charter':
                try:events=self._service_command_locked({'op':'PetitionOpen','item':instance['instance_id']})
                except ValueError as exc:return {'error':str(exc)}
                result=self.snapshot_locked();result['client_events']=events;return result
            if definition.get('equip_slot'):return self.equip_item(instance['instance_id'])
            return {'error':'ITEM_NO_USE_EFFECT'}

    def _tick_auto_attack_locked(self):
        if not self._actions.auto_attack:return
        if not self._combat_state.get('actors',{}).get('player',{}).get('alive',True):
            self._actions.auto_attack=False;return
        row=self._selected_interaction_locked()
        if not row or row.get('dead') or not row.get('attackable'):
            self._actions.auto_attack=False;return
        if row['kind']=='NATURE':
            if row['distance_m']<=3.75 and self._nature.states.get(row['id'],{}).get('attack_after',0)<=self._sim_time:
                self.nature_action(row['id'],'ATTACK')
        else:
            actor=self._combat_state.get('actors',{}).get('player',{})
            if not actor.get('alive',True):self._actions.auto_attack=False;return
            if row['distance_m']<=self._player_combat_profile_locked()['attack_range_m']+.35 and actor.get('cooldown_until',0)<=self._sim_time:self.attack(row['id'])
