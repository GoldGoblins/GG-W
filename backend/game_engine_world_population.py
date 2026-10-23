"""Persistent regional residents, schedules, work, trade and small encounters.

Full-world logical population is independent of the renderer. One regional
lane advances at each half-second tick. Only a bounded nearby cast receives
poses/terrain samples, with paced activation and a continuous route clock.
"""
import copy
import math
from backend import game_engine_life as life,game_engine_world_places as places

VISUAL_LIMIT=12
VISUAL_RADIUS=life.RENDER_RADIUS_M


class WorldPopulation:
    def __init__(self):
        self.spawns={};self.regions={};self.index={};self.active=[];self.admit_bucket=None
        self.last_tick=-1.;self.lane=0;self.events=[];self.encounters={}
        self.locations={p['id']:p for p in places.catalog()['places']}
        self.stocks={key:dict(food=12,wood=6,ore=6,coins=40) for key in self.locations}
        self.people={}
        for appearance_index,raw in enumerate(places.catalog()['residents']):
            s=dict(raw,x=raw['stops'][0][0],z=raw['stops'][0][1],route='AUTHORED_WORLD_ROUTINE',
                   route_offset_s=raw['offset_s'],waypoints=[dict(x=p[0],z=p[1],wait_s=p[2],activity=p[3]) for p in raw['stops']],
                   scale=(.86,1,.86),color='#bca87c',sense_radius=4)
            life.prepare_routine(s);self.spawns[s['id']]=s
            self.regions.setdefault(s['region_id'],[]).append(s['id'])
            points=s['waypoints'];low=[min(p[k] for p in points)-VISUAL_RADIUS for k in ('x','z')]
            high=[max(p[k] for p in points)+VISUAL_RADIUS for k in ('x','z')]
            for x in range(math.floor(low[0]/512),math.floor(high[0]/512)+1):
                for z in range(math.floor(low[1]/512),math.floor(high[1]/512)+1):self.index.setdefault((x,z),[]).append(s['id'])
            self.people[s['id']]=dict(name=s['name'],role=s['role'],health=60,alive=True,respawn_at=0,
                home=dict(x=s['x'],z=s['z']),needs=dict(hunger=.25,fatigue=.2),
                inventory=dict(food=2,wood=0,ore=0,coins=5),memory=[],last_update_s=0,visit=None,
                epoch=0,reset_offset=False,work_count=0,trade_count=0)
            self.people[s['id']]['appearance_index']=int(raw.get('appearance_index',appearance_index))

    def position(self,identity,t):
        person=self.people[identity];spawn=self.spawns[identity]
        if not person['alive']:
            return dict(**person['death_position'],vx=0.,vz=0.,activity='DEAD',stop=0)
        if person['reset_offset']:spawn=dict(spawn,route_offset_s=0)
        effective,paused=self.route_time(identity,t)
        point=life.routine_state(spawn,effective)
        if paused:point.update(vx=0.,vz=0.,activity='TALKING')
        return point

    def route_time(self,identity,t):
        person=self.people[identity];pause=person.get('talk_pause')
        held=max(0,min(t,pause['until'])-pause['start']) if pause else 0
        return max(0,t-person['epoch']-held),bool(pause and pause['start']<=t<pause['until'])

    def pause_for_talk(self,identity,t):
        person=self.people[identity];pause=person.get('talk_pause')
        if pause and t>=pause['until']:self.resume_route(identity,t)
        if not person.get('talk_pause'):person['talk_pause']=dict(start=t,until=t+30)
        else:person['talk_pause']['until']=t+30

    def resume_route(self,identity,t):
        person=self.people[identity];pause=person.pop('talk_pause',None)
        if pause:person['epoch']+=max(0,min(t,pause['until'])-pause['start'])

    def select(self,t,x,z):
        bucket=math.floor(t*4)
        if bucket==self.admit_bucket:
            self.active=[i for i in self.active if math.hypot(self.position(i,t)['x']-x,self.position(i,t)['z']-z)<VISUAL_RADIUS+24]
            return tuple(self.active)
        self.admit_bucket=bucket
        candidates=[]
        for identity in self.index.get((math.floor(x/512),math.floor(z/512)),()):
            p=self.position(identity,t);distance=math.hypot(p['x']-x,p['z']-z)
            if distance<=VISUAL_RADIUS:candidates.append((distance,identity))
        keep={i for d,i in candidates}
        self.active=[i for i in self.active if i in keep]
        admitted=0
        for _,identity in sorted(candidates):
            if len(self.active)>=VISUAL_LIMIT:break
            if identity not in self.active:
                self.active.append(identity)
                # At most two new rigs per admission interval, never 312.
                admitted+=1
                if admitted>=2:break
        return tuple(self.active)

    def rows(self,t,x,z,height_at):
        rows=[]
        for identity in self.active:
            s=self.spawns[identity];person=self.people[identity]
            spawn=dict(s,route_offset_s=0) if person['reset_offset'] else s
            effective,paused=self.route_time(identity,t)
            row=life.proxy_rows([spawn],effective,player_x=x,player_z=z,
                terrain_height=height_at,render_radius_m=VISUAL_RADIUS+24)[0]
            if paused and not row['hidden']:
                row.update(speed=0.,yaw=math.atan2(x-row['x'],z-row['z']),
                    animation=life.animation_contract.build_pose(sim_time=t,horizontal_speed=0,grounded=True))
                row['life'].update(activity='TALKING')
            if not person['alive']:
                row.update(hidden=True,animation=None,**person['death_position'])
            row['individual']=dict(id=identity,name=person['name'],role=person['role'],
                home=dict(person['home']),needs=dict(person['needs']),memory=copy.deepcopy(person['memory']),inventory=dict(person['inventory']),
                appearance_index=person['appearance_index'])
            row['life'].update(region=s['region_id'],place_id=s['place_id'])
            rows.append(row)
        return rows

    def remember(self,identity,event,t):
        person=self.people[identity];person['memory'].append(dict(kind=event,time_s=round(t,3)))
        person['memory']=person['memory'][-8:]

    def tick(self,t):
        if t-self.last_tick<.5:return
        self.last_tick=t
        if not self.regions:return
        region=sorted(self.regions)[self.lane%len(self.regions)];self.lane+=1
        ids=self.regions[region];positions={}
        for identity in ids:
            person=self.people[identity];s=self.spawns[identity]
            if person.get('talk_pause') and t>=person['talk_pause']['until']:self.resume_route(identity,t)
            dt=max(0,min(8,t-person['last_update_s']));person['last_update_s']=t
            if not person['alive']:
                if t<person['respawn_at']:continue
                person.update(alive=True,health=60,epoch=t,reset_offset=True,visit=None)
                person.pop('talk_pause',None)
                self.remember(identity,'RESPAWN_AT_SAVED_HOME',t)
            p=self.position(identity,t);positions[identity]=p
            person['needs']['hunger']=min(1,person['needs']['hunger']+dt*.003)
            person['needs']['fatigue']=max(0,min(1,person['needs']['fatigue']+dt*(-.008 if p['activity']=='RESTING' else .002)))
            if person['needs']['hunger']>.55 and person['inventory']['food']:
                person['inventory']['food']-=1;person['needs']['hunger']=max(0,person['needs']['hunger']-.45)
                self.remember(identity,'ATE_CARRIED_FOOD',t)
            if p['activity'] in ('TRAVELING','TALKING'):continue
            period=s['_routine_period_s'];offset=0 if person['reset_offset'] else s['route_offset_s']
            cycle=math.floor((self.route_time(identity,t)[0]+offset)/period)
            visit=(cycle,p['stop'],p['activity'])
            if person['visit']==visit:continue
            person['visit']=visit
            destination=s.get('destination_id') if p['stop']==len(s['waypoints'])-1 else None
            place_id=destination or s['place_id'];stock=self.stocks[place_id]
            if p['activity']=='WORKING':
                good=self.locations[place_id]['production'];stock[good]=min(999,stock[good]+2)
                person['work_count']+=1
                if stock['coins']>0:stock['coins']-=1;person['inventory']['coins']+=1
                self.remember(identity,'PRODUCED_'+good.upper(),t)
            if p['activity']=='TRADING' and stock['food']>0 and person['inventory']['coins']>0:
                stock['food']-=1;stock['coins']+=1
                person['inventory']['food']+=1;person['inventory']['coins']-=1
                person['trade_count']+=1;self.remember(identity,'BOUGHT_FOOD_AT_'+place_id,t)
            if s['role']=='CARAVANEER':
                good=self.locations[s['place_id']]['production']
                if destination and person['inventory'][good]>0 and stock['coins']>=2 and stock[good]<999:
                    stock[good]+=1;person['inventory'][good]-=1;person['inventory']['coins']+=2;stock['coins']-=2
                    self.remember(identity,'DELIVERED_'+good.upper(),t)
                elif not destination and stock[good]>0:
                    stock[good]-=1;person['inventory'][good]+=1
                    self.remember(identity,'LOADED_'+good.upper(),t)
        # Bound social/hostile encounters independently of the player's
        # location. They change carried goods/health and write real memories.
        groups={};pairs=0
        # Forget expired cooldowns; remembered encounters live in the saved
        # per-person journals. This transient lookup stays bounded.
        self.encounters={key:stamp for key,stamp in self.encounters.items() if t-stamp<20}
        for identity,p in positions.items():groups.setdefault((math.floor(p['x']/12),math.floor(p['z']/12)),[]).append(identity)
        for a,p in positions.items():
            bx,bz=math.floor(p['x']/12),math.floor(p['z']/12)
            for dx,dz in ((0,0),(-1,0),(1,0),(0,-1),(0,1),(-1,-1),(1,1),(-1,1),(1,-1)):
                for b in groups.get((bx+dx,bz+dz),()):
                    if a>=b or not self.people[a]['alive'] or not self.people[b]['alive']:continue
                    key=a+'|'+b
                    if t-self.encounters.get(key,-100)<20 or math.hypot(p['x']-positions[b]['x'],p['z']-positions[b]['z'])>5:continue
                    self.encounters[key]=t;pa,pb=self.people[a],self.people[b]
                    bandit=a if pa['role']=='BANDIT' else b if pb['role']=='BANDIT' else None
                    event='MET_NEIGHBOUR'
                    if bandit and self.spawns[a]['place_id']!=self.spawns[b]['place_id']:
                        other=b if bandit==a else a;victim=self.people[other];outlaw=self.people[bandit]
                        if victim['role'] in ('GUARD','ADVENTURER','HUNTER'):
                            outlaw['health']-=20;victim['health']-=5;event='DEFENDED_ROAD'
                        elif victim['inventory']['food']:
                            victim['inventory']['food']-=1;outlaw['inventory']['food']+=1;event='ROAD_ROBBERY'
                        for identity in (a,b):
                            actor=self.people[identity]
                            if actor['health']<=0:
                                actor.update(alive=False,respawn_at=t+45,death_position={k:positions[identity][k] for k in ('x','z')})
                    self.remember(a,event,t);self.remember(b,event,t)
                    self.events.append(dict(kind=event,a=a,b=b,time_s=round(t,3)));self.events=self.events[-64:]
                    pairs+=1
                    if pairs>=2:return

    def save(self):
        return copy.deepcopy(dict(schema='gg.world-population.v1',people=self.people,stocks=self.stocks,
            events=self.events,encounters=self.encounters,last_tick=self.last_tick,lane=self.lane))

    def restore(self,payload):
        if not isinstance(payload,dict) or payload.get('schema')!='gg.world-population.v1':return
        for identity in self.people:
            if identity in payload.get('people',{}):self.people[identity]={**self.people[identity],**copy.deepcopy(payload['people'][identity])}
        for identity in self.stocks:
            if identity in payload.get('stocks',{}):self.stocks[identity]=copy.deepcopy(payload['stocks'][identity])
        self.events=copy.deepcopy(payload.get('events',[]))[-64:]
        self.encounters=copy.deepcopy(payload.get('encounters',{}));self.last_tick=float(payload.get('last_tick',-1));self.lane=int(payload.get('lane',0))
        self.active=[];self.admit_bucket=None

    def view(self):
        return dict(population=len(self.people),visible=len(self.active),visual_budget=VISUAL_LIMIT,
            regions=len(self.regions),places=len(self.locations),work_visits=sum(p['work_count'] for p in self.people.values()),
            trade_visits=sum(p['trade_count'] for p in self.people.values()),recent_events=copy.deepcopy(self.events[-8:]))

    def dialogue_tree(self,identity):
        """One nearby conversation, using this person's real home and goods."""
        person=self.people[identity];spawn=self.spawns[identity];home=self.locations[spawn['place_id']]
        descriptions={
            'TOWN':'We keep the market, homes and watch together here.',
            'MILL':'The mill supplies wood to the neighbouring settlements.',
            'WORKS':'The crews here work the ore and keep the road supplied.',
            'WATCH':'This watch marks the road and keeps an eye on travellers.',
            'FARM':'The fields supply food to the market and passing caravans.',
            'INN':'Travellers rest here before returning to the road.',
            'RUINS':'The old stones were here before our houses. Follow the lamps back to the road.',
            'BANDIT_CAMP':'Our camp watches the road. Travellers should mind what they carry.'}
        job={
            'WORKER':'I work here, carry my own food and return to my home.',
            'MERCHANT':'I visit the market for food. The supplies come from our workers and caravans.',
            'CARAVANEER':'I carry supplies between settlements and walk the same road home.',
            'GUARD':'I watch this settlement and help defend travellers when outlaws come near.',
            'BANDIT':'I keep to our camp, but the passing traffic interests me.',
            'SCOUT':'I scout the paths near my home.',
            'ADVENTURER':'I travel the road in both directions and watch for trouble.',
            'VILLAGER':'I live here and walk the paths around my home.',
            'HUNTER':'I watch the paths outside the settlement.'}.get(person['role'],'I live here.')
        roads=[r for r in places.catalog()['roads'] if spawn['place_id'] in (r['from_place'],r['to_place'])]
        destinations=[self.locations[r['to_place'] if r['from_place']==spawn['place_id'] else r['from_place']]['name'] for r in roads]
        route='The marked roads lead to '+', '.join(destinations[:3])+'.' if destinations else 'The lamps mark the way back home.'
        stock=self.stocks[spawn['place_id']]
        work=f"{job} I carry {person['inventory']['food']} food. Our stores hold {stock['food']} food, {stock['wood']} wood and {stock['ore']} ore."
        nodes={'start':dict(id='start',text=f"I'm {person['name']}. My home is {home['name']}.",choices=[
            dict(id='place',label='Ask about this place',next='place'),
            dict(id='work',label='Ask about their work',next='work'),
            dict(id='roads',label='Ask where the roads lead',next='roads'),
            dict(id='leave',label='Leave',next='end')]),
            'end':dict(id='end',text='Safe travels.',choices=[])}
        for key,text in (('place',descriptions[home['kind']]),('work',work),('roads',route)):
            nodes[key]=dict(id=key,text=text,choices=[dict(id='back',label='Ask something else',next='start'),dict(id='leave',label='Leave',next='end')])
        return dict(id=identity,speaker=person['name'],start='start',nodes=nodes)
