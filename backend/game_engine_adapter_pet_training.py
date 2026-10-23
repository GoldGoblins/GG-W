"""Local pet training, diets, loyalty and level progression in the shared simulation."""
import math
from backend import game_engine_items as items, game_engine_combat as combat
from backend.game_engine_adapter_local_client import integer

STRIKE, BITE, GUARD = 0x800101, 0x800102, 0x800103
SPELLS = {
    STRIKE: dict(id=STRIKE, name='Strike', level=1, points=0, cost=0, description='Basic melee attack.', icon='Interface\\Icons\\Ability_Druid_FerociousBite'),
    BITE: dict(id=BITE, name='Bite', level=2, points=1, cost=1000, description='Melee attack with 20% additional damage.', icon='Interface\\Icons\\Ability_Racial_Cannibalize'),
    GUARD: dict(id=GUARD, name='Guard', level=3, points=2, cost=2000, passive=True, description='Passive: adds 3 armor.', icon='Interface\\Icons\\Ability_Defend'),
}
HERBIVORES = {'rabbit', 'sheep', 'goat', 'deer', 'squirrel'}

class PetTrainingMixin:
    def _pet_swimming_locked(self,pet):
        world=getattr(self,'_engine_world',None)
        if world is None:
            floor=self._terrain_height_locked(pet['x'],pet['z'])
            liquid=self._water_sample_locked(pet['x'],pet['z'])
        else:
            query=world.query(pet['x'],pet['y']+.65,pet['z'])
            if not query['loaded'] or query['impassable']:return False
            floor=query['height'];liquid=world.water_sample(pet['x'],pet['y'],pet['z'])
        surface=liquid.get('height_m',-100001.)
        if liquid.get('has_surface') is False and liquid.get('body_kind','NONE')!='NONE':return True
        return (type(surface) in (int,float) and math.isfinite(surface) and abs(surface)<=2_000_000
                and liquid.get('has_surface',True) and (floor is None or surface-floor>.8) and pet['y']<=surface+.35)

    def _pet_move_locked(self,pet,x,z):
        """Keep owned animals on real resident walking hulls without player state."""
        world=getattr(self,'_engine_world',None)
        if world is None:
            floor=self._terrain_height_locked(x,z)
            y=pet['y'] if self._pet_swimming_locked(pet) or pet['y']>floor+.1 else floor
            return x,y,z
        from backend.game_engine_adapter_locomotion import move
        return move(world,(pet['x'],pet['y'],pet['z']),x,z,swimming=self._pet_swimming_locked(pet))

    def _pet_waypoint_locked(self,pet,x,z):
        world=getattr(self,'_engine_world',None)
        if world is None:return x,z
        from backend.game_engine_adapter_locomotion import routes
        waypoint=routes(world).waypoint('pet:'+str(pet['number']),
            (pet['x'],pet['y'],pet['z']),(x,pet['y'],z),self._sim_time,swimming=self._pet_swimming_locked(pet))
        return waypoint[0],waypoint[2]

    def _pet_physics_locked(self,pet,actor,dt):
        world=getattr(self,'_engine_world',None)
        if world is not None:
            from backend.game_engine_adapter_locomotion import motion
            position,velocity,mode,impact=motion(world,(pet['x'],pet['y'],pet['z']),pet.get('vy',0.),dt,alive=actor.get('alive',True))
            pet['x'],pet['y'],pet['z']=position
            if velocity or 'vy' in pet or mode=='SWIM':pet['vy']=velocity
            if actor.get('alive',True) and impact>8:
                dealt,absorbed=combat.deal_damage(self._combat_state,actor,actor['max_health']*min(1.,(impact-8.)/20.),'environment',self._sim_time)
                self._append_event_locked('PET_FALL_DAMAGE',pet['name'],actor_id='pet:'+str(pet['number']),payload=dict(damage=dealt,absorbed=absorbed))
            return
        if world is None:
            floor=self._terrain_height_locked(pet['x'],pet['z'])
            water=self._water_sample_locked(pet['x'],pet['z'])
        else:
            query=world.query(pet['x'],pet['y']+.65,pet['z'])
            if not query['loaded'] or query['impassable']:return
            floor=query['height'];water=world.water_sample(pet['x'],pet['y'],pet['z'])
        surface=water.get('height_m',-100001.)
        if actor.get('alive',True) and self._pet_swimming_locked(pet):
            # Same real liquid sampler; swimming does not invent a walking floor.
            target=surface-.45;pet['y']+=max(-1.8*dt,min(1.8*dt,target-pet['y']))
            pet['vy']=0.;return
        if floor is not None and pet['y']<=floor+.08:
            pet['y']=floor
            if 'vy' in pet:pet['vy']=0.
            return
        speed=max(-30.,pet.get('vy',0.)-9.81*dt)
        next_y=pet['y']+speed*dt
        if floor is not None and next_y<=floor:
            pet['y']=floor;pet['vy']=0.
            if actor.get('alive',True) and -speed>8:
                amount=actor['max_health']*min(1.,(-speed-8.)/20.)
                dealt,absorbed=combat.deal_damage(self._combat_state,actor,amount,'environment',self._sim_time)
                self._append_event_locked('PET_FALL_DAMAGE',pet['name'],actor_id='pet:'+str(pet['number']),
                    payload=dict(damage=dealt,absorbed=absorbed))
        else:pet['y']=next_y;pet['vy']=speed

    def _suspend_companion_locked(self):
        number=self._services['active_pet'];pet=self._active_pet_locked()
        if pet:pet.update(target='',command=1)
        self._services['active_pet']=0;self._publish_companions_locked();return number

    def _resume_companion_locked(self,number):
        pet=next((p for p in self._services['pets'] if p['number']==number),None)
        if not pet:return
        self._services['active_pet']=number
        pet.update(target='',command=1,x=self._x[0]+1.5,z=self._z[0]+1.5,y=self._terrain_height_locked(self._x[0]+1.5,self._z[0]+1.5))
        self._publish_companions_locked()

    def _pet_training_defaults_locked(self, pet):
        pet.setdefault('learned', {str(STRIKE): bool(pet.get('autocast'))})
        pet.setdefault('happiness', 600000.)
        pet.setdefault('loyalty', 1)
        pet.setdefault('loyalty_progress', 0.)
        pet.setdefault('training_spent', 0)
        pet.setdefault('pending_spell', STRIKE)
        pet.setdefault('resistances', [0] * 7)
        if (not isinstance(pet['learned'], dict) or len(pet['learned'])>len(SPELLS) or str(STRIKE) not in pet['learned']
                or any(int(k) not in SPELLS or type(v) is not bool for k,v in pet['learned'].items())
                or type(pet['happiness']) not in (int,float) or not 0 <= pet['happiness'] <= 1000000 or not math.isfinite(pet['happiness'])
                or type(pet['loyalty']) is not int or not 1 <= pet['loyalty'] <= 6
                or type(pet['loyalty_progress']) not in (int,float) or not math.isfinite(pet['loyalty_progress']) or not -300<=pet['loyalty_progress']<=300
                or type(pet['pending_spell']) is not int or str(pet['pending_spell']) not in pet['learned']
                or not isinstance(pet['resistances'],list) or len(pet['resistances'])!=7 or any(type(v) is not int or not 0<=v<=1000 for v in pet['resistances'])
                or type(pet['training_spent']) is not int or not 0<=pet['training_spent']<=pet['level']*5):
            raise ValueError('PET_TRAINING_SAVE_INVALID')
        for key in pet['learned']:
            if SPELLS[int(key)].get('passive'):pet['learned'][key]=False
        if SPELLS[pet['pending_spell']].get('passive'):pet['pending_spell']=STRIKE

    def _pet_training_command_locked(self, row):
        op=row['op'];pet=self._active_pet_locked()
        if op in ('TrainerOpen','TrainerClose'):
            if op=='TrainerOpen':
                if not pet:raise ValueError('PET_ACTIVE_COMPANION_REQUIRED')
                identity=self._service_person_locked(row.get('target','target'),nearby=True)
                if identity=='player':raise ValueError('TRAINER_OTHER_PERSON_REQUIRED')
                self._service_generation+=1
                self._service_windows['trainer']=True;self._services['trainer_target']=identity;self._services['trainer_kind']='PET'
                return [{'event':'TRAINER_SHOW','args':[]}]
            self._service_session_locked(row,'trainer');self._service_windows['trainer']=False
            return [{'event':'TRAINER_CLOSED','args':[]}]
        if not pet:raise ValueError('PET_ACTIVE_COMPANION_REQUIRED')
        self._pet_training_defaults_locked(pet)
        if op=='PetFeed':
            actor=combat.ensure_actor(self._combat_state,'pet:'+str(pet['number']),self._pet_profile_locked(pet))
            if not actor['alive'] or pet['target']:raise ValueError('PET_FEED_OUT_OF_COMBAT_AND_ALIVE_REQUIRED')
            food=self._item_instance_locked(row.get('item'))
            definition=items.definition(self._item_catalog,food.get('definition_id')) if food else None
            if not definition or 'FOOD' not in definition.get('tags',[]):raise ValueError('PET_FOOD_REQUIRED')
            diet='PLANTS' if pet['species'] in HERBIVORES else 'MEAT'
            food_type=definition.get('pet_food_type','ALL')
            if food_type not in (diet,'ALL'):raise ValueError('PET_FOOD_WRONG_DIET')
            if not self._consume_inventory_item_locked(food):raise ValueError('PET_FOOD_NOT_IN_BAGS')
            pet['happiness']=min(1000000.,pet['happiness']+350000.)
            actor['health']=min(actor['max_health'],actor['health']+actor['max_health']*.1)
        elif op=='TrainerBuy':
            self._service_session_locked(row,'trainer')
            self._service_person_locked(self._services.get('trainer_target'),nearby=True)
            spell=integer(row.get('spell_id'),1,0xffffff);data=SPELLS.get(spell)
            if not data or str(spell) in pet['learned']:raise ValueError('PET_TRAINING_ALREADY_KNOWN_OR_UNKNOWN')
            if pet['level']<data['level']:raise ValueError('PET_TRAINING_LEVEL_REQUIRED')
            total=max(0,pet['level']*(pet['loyalty']-1))
            if total-pet['training_spent']<data['points']:raise ValueError('PET_TRAINING_POINTS_REQUIRED')
            self._service_money_locked(delta=-data['cost'])
            pet['learned'][str(spell)]=False;pet['training_spent']+=data['points']
            empty=next((i for i in range(3,7) if pet['slots'][i]==0),None)
            if empty is not None and not data.get('passive'):pet['slots'][empty]=(128<<24)|spell
        elif op=='PetUnlearn':
            self._service_session_locked(row,'trainer')
            self._service_person_locked(self._services.get('trainer_target'),nearby=True)
            if len(pet['learned'])<=1:raise ValueError('PET_NO_TRAINED_ABILITIES')
            self._service_money_locked(delta=-1000)
            pet['learned']={str(STRIKE):False};pet['training_spent']=0;pet['autocast']=False
            pet['slots']=[word if word&0xffffff not in (BITE,GUARD) else 0 for word in pet['slots']]
        else:raise ValueError('PET_TRAINING_COMMAND_UNKNOWN')
        return [{'event':e,'args':[]} for e in ('PET_UI_UPDATE','PET_BAR_UPDATE','TRAINER_UPDATE')]

    def _pet_training_view_locked(self, pet):
        self._pet_training_defaults_locked(pet)
        bucket=1 if pet['happiness']<333333 else 2 if pet['happiness']<666666 else 3
        return dict(happiness=bucket, damage_percentage={1:75,2:100,3:125}[bucket],
            loyalty=pet['loyalty'], loyalty_rate=-1 if bucket==1 else 1 if bucket==3 else 0,
            training_total=max(0,pet['level']*(pet['loyalty']-1)), training_spent=pet['training_spent'],
            next_xp=100*pet['level'], food_types=['Plants'] if pet['species'] in HERBIVORES else ['Meat'],
            learned=[dict(SPELLS[int(k)],autocast=v) for k,v in pet['learned'].items()])

    def _trainer_view_locked(self):
        if self._services.get('trainer_kind')=='PROFESSION':return self._profession_trainer_view_locked()
        pet=self._active_pet_locked()
        if not pet or not self._service_windows.get('trainer'):return dict(open=False,rows=[])
        self._pet_training_defaults_locked(pet)
        total=max(0,pet['level']*(pet['loyalty']-1));money=self._service_money_locked()
        rows=[dict(s,category='used' if str(k) in pet['learned'] else 'available' if pet['level']>=s['level']
                and total-pet['training_spent']>=s['points'] and money>=s['cost'] else 'unavailable')
              for k,s in SPELLS.items()]
        return dict(open=True,rows=rows,target=self._services.get('trainer_target',''))

    def _tick_pet_training_locked(self, pet, dt):
        self._pet_training_defaults_locked(pet)
        actor=self._combat_state.get('actors',{}).get('pet:'+str(pet['number']),{})
        if not actor.get('alive',True):return
        pet['happiness']=max(0.,pet['happiness']-max(0.,dt)*100.)
        bucket=1 if pet['happiness']<333333 else 2 if pet['happiness']<666666 else 3
        pet['loyalty_progress']+=max(0.,dt)*(1 if bucket==3 else -1 if bucket==1 else 0)
        if pet['loyalty_progress']>=300 and pet['loyalty']<6:
            pet['loyalty']+=1;pet['loyalty_progress']=0.
        elif pet['loyalty_progress']<=-300:
            pet['loyalty']=max(1,pet['loyalty']-1);pet['loyalty_progress']=0.
        if pet['xp']>=100*pet['level'] and pet['level']<self._progression.get('level',1):
            pet['xp']-=100*pet['level'];pet['level']+=1
