"""Bounded nearby nature simulation and authoritative harvest state.

Stable identities and seeded paths survive cell eviction. Cooldowns and
remains belong to gameplay, independently of decorative flora residency.
"""
from __future__ import annotations
import math
import hashlib
from collections import OrderedDict
from backend.game_engine_nature_catalog import SPECIES, PLANTS, ANIMALS, LABELS
from backend.game_engine_ecology import biome_at, unit
from backend import game_engine_planet as planet, game_engine_world as world
from backend.game_engine_asset_variations import VARIANTS,variant_for

SCHEMA="gg.game-engine.nature.v1"
CELL_M=64
MAX_ANIMALS=48
MAX_CELLS=128
MAX_STATES=2048
UPDATE_S=1/60
PARTS=("body","motion_a","motion_b")
def parts_for(species):
    return (*PARTS,"coat") if species=="sheep" else PARTS if species in ANIMALS else ("body",)
GROUP_KEYS=tuple(f"{s}:{p}"+('' if v==0 else f'-v{v}') for s in SPECIES for p in parts_for(s) for v in range(VARIANTS))

def visual_key(row,part):
    variant=variant_for(row['id'])
    return row['species']+':'+part+('' if variant==0 else f'-v{variant}')


class NatureWorld:
    def __init__(self,seed):
        self.seed=seed;self.cells=OrderedDict();self.states={};self.groups={}
        self.rows=[];self.revision=0;self._stamp=None;self.last_result={}
        self._fixed_revision = None
        self._garden_anchors = None
        self._village_anchors = None

    def visible(self,identity,now):
        return self.states.get(identity,{}).get("hidden_until",0)<=now

    def _cell(self,cx,cz,height_at):
        key=(cx,cz)
        if key in self.cells:
            self.cells.move_to_end(key);return self.cells[key]
        rows=[]
        for i in range(4):
            x=(cx+.12+.76*unit(cx,cz,i*11+1,self.seed))*CELL_M
            z=(cz+.12+.76*unit(cx,cz,i*11+2,self.seed))*CELL_M
            if not (planet.MAP_BOUNDS_M['min_x']<=x<=planet.MAP_BOUNDS_M['max_x'] and
                    planet.MAP_BOUNDS_M['min_z']<=z<=planet.MAP_BOUNDS_M['max_z']):continue
            h=height_at(x,z);biome=biome_at(x,z,h)
            domain="WATER" if h<-.8 else ("AIR" if i==3 else "LAND")
            if domain=="LAND" and (h<1.1 or math.hypot(height_at(x+1,z)-h,height_at(x,z+1)-h)>.85):continue
            choices=[s for s in ANIMALS if SPECIES[s]['domain']==domain and
                     (biome in SPECIES[s]['biomes'] or domain=="WATER")]
            if not choices:continue
            species=choices[int(unit(cx,cz,i*11+3,self.seed)*len(choices))]
            rows.append(self._anchor(f"nature:{cx}:{cz}:{i}",species,x,z,h,unit(cx,cz,i+20,self.seed)))
        self.cells[key]=rows
        while len(self.cells)>MAX_CELLS:self.cells.popitem(last=False)
        return rows

    def _anchor(self,identity,species,x,z,h,phase):
        return {"id":identity,"species":species,"anchor_x":x,"anchor_z":z,
                "ground_height_m":h,"phase":phase*math.tau,"scale":.88+.24*phase,"tint":1}

    def garden(self,height_at):
        return [self._anchor("nature:garden:"+s,s,8+(i%4)*3.2,-8+(i//4)*3.8,
                             height_at(8+(i%4)*3.2,-8+(i//4)*3.8),i/12)
                for i,s in enumerate(PLANTS)]

    def _starter_animals(self,height_at):
        species=list(ANIMALS)[:10]+["gull","songbird","parrot","bee","butterfly"]
        return [self._anchor("nature:village:"+s,s,30+12*math.cos(i*2.4),14+17*math.sin(i*2.4),
                             height_at(30+12*math.cos(i*2.4),14+17*math.sin(i*2.4)),i/len(species))
                for i,s in enumerate(species)]

    def update(self,x,z,now,height_at,flora_rows,terrain_revision=0,*,static_height_at=None):
        stamp=(int(now/UPDATE_S),int(x/8),int(z/8),terrain_revision,self.revision)
        if self._stamp==stamp:return
        if self._stamp and self._stamp[3]!=terrain_revision:self.cells.clear()
        if self._fixed_revision != terrain_revision:
            self._fixed_revision = terrain_revision
            self._garden_anchors = self._village_anchors = None
        self.rows=[];groups={}
        fixed_height = static_height_at if static_height_at is not None else height_at
        plants=[r for r in flora_rows if r['species'] in PLANTS]
        from backend.game_engine_canopy import produce_anchors
        plants+=produce_anchors(x,z,fixed_height)
        if math.hypot(x-14,z)<100:
            if self._garden_anchors is None:self._garden_anchors = self.garden(fixed_height)
            plants+=self._garden_anchors
        for r in plants:
            if not self.visible(r['id'],now):continue
            if math.hypot(r.get('x',r.get('anchor_x',0))-x,r.get('z',r.get('anchor_z',0))-z)>100:continue
            row=dict(r)
            if 'x' not in row:row.update(x=r['anchor_x'],z=r['anchor_z'],y=r['ground_height_m'],yaw=0)
            else:row['y']=r['ground_height_m']
            self.rows.append(row)
            if r['id'].startswith(('nature:garden:','nature:produce:')):
                groups.setdefault(visual_key(r,'body'),[]).append(self._render(row))
        cx,cz=math.floor(x/CELL_M),math.floor(z/CELL_M)
        anchors=[]
        for dz in (-1,0,1):
            for dx in (-1,0,1):anchors+=self._cell(cx+dx,cz+dz,fixed_height)
        if math.hypot(x-30,z-14)<110:
            if self._village_anchors is None:self._village_anchors = self._starter_animals(fixed_height)
            anchors+=self._village_anchors
        anchors.sort(key=lambda r:(math.hypot(r['anchor_x']-x,r['anchor_z']-z),r['id']))
        for a in anchors[:MAX_ANIMALS]:
            if not self.visible(a['id'],now):continue
            s=SPECIES[a['species']];state=self.states.get(a['id'],{})
            if state.get('dead',False) and state.get('respawn_at',0)<=now:
                self.states.pop(a['id'],None);state={}
            phase=a['phase'];clock=now+phase*3
            cycle=math.floor(clock/20);within=clock-cycle*20
            t=.42*(cycle*16+min(within,16))+phase
            idle=within>=16 or state.get('calm_until',0)>now or state.get('dead',False)
            radius=2.8 if s['domain']=='LAND' else 4
            px=a['anchor_x']+radius*(.72*math.sin(t)+.25*math.sin(2.7*t+phase))
            pz=a['anchor_z']+radius*.6*math.sin(1.7*t+phase)
            if state.get('calm_until',0)>now-1:
                mix=max(0,min(1,now-state.get('calm_until',now)))
                px=state.get('calm_x',px)*(1-mix)+px*mix;pz=state.get('calm_z',pz)*(1-mix)+pz*mix
            if state.get('flee_until',0)>now:
                elapsed=max(0,min(2,now-state.get('flee_start',now)))
                offset=math.sin(elapsed*math.pi/2)*3
                px+=state.get('flee_dx',0)*offset;pz+=state.get('flee_dz',0)*offset
            h=height_at(px,pz)
            if s['domain']=='WATER':
                if h>-.8:px,pz,h=a['anchor_x'],a['anchor_z'],a['ground_height_m']
                y=max(h+.35,-.65-(.5+.3*math.sin(t)))
                if y>-.25:continue
            else:
                if h<1.1 or abs(h-a['ground_height_m'])>1.5:
                    px,pz,h=a['anchor_x'],a['anchor_z'],a['ground_height_m']
                y=h+(1.1+.8*(1+math.sin(t*1.9)) if s['domain']=='AIR' else 0)
                if s['domain']=='LAND' and not idle:y+=.015*math.sin(now*8+phase)
            row={**a,'x':px,'z':pz,'y':y,'yaw':math.degrees(math.atan2(math.cos(t),1.02*math.cos(t*1.7+phase))),
                 'behavior':'DEAD' if state.get('dead') else 'IDLE' if idle else 'FLEE' if state.get('flee_until',0)>now else
                 {'LAND':'WANDER','AIR':'FLY','WATER':'SWIM'}[s['domain']]}
            if state.get('dead'):row['roll']=85
            if state.get('dead'):
                row.update(x=state.get('death_x',px),y=state.get('death_y',y),z=state.get('death_z',pz))
                ground=height_at(row['x'],row['z'])
                floor=max(ground+.05,-.25) if s['domain']=='WATER' else ground+.05
                row['y']=max(floor,row['y']-4.9*max(0,now-state.get('death_at',now))**2)
            self.rows.append(row)
            for p in parts_for(a['species']):
                if p=='coat' and state.get('cooldowns',{}).get('SHEAR',0)>now:continue
                part=self._render(row)
                motion=0 if idle else math.sin(now*(16 if a['species'] in {'bee','butterfly'} else 7)+phase)
                if p in {'motion_a','motion_b'}:
                    sign=1 if p=='motion_a' else -1
                    if s['domain']=='AIR':part['roll']=part.get('roll',0)+motion*sign*38
                    elif s['domain']=='WATER':part['yaw']+=motion*sign*16
                    else:part['pitch']=motion*sign*18
                groups.setdefault(visual_key(a,p),[]).append(part)
        self.groups=groups;self.revision+=1
        self._stamp=(*stamp[:4],self.revision)

    def _render(self,r):
        row=dict(r);radius=world.DEFAULT_PLANET_RADIUS_METERS
        row['y']=math.sqrt(max(1,(radius+r['y'])**2-r['x']**2-r['z']**2))-radius
        return row

    def target(self,x,y,z,now,owned,identity=''):
        choices=[]
        for row in self.rows:
            if identity and row['id']!=identity:continue
            s=SPECIES[row['species']]
            distance=math.sqrt((row['x']-x)**2+(row['z']-z)**2+(row['y']+.2-y)**2)
            radius=8 if s['domain'] in {'AIR','WATER'} else 3.75
            if distance>radius:continue
            choices.append((distance,row['id'],row))
        if not choices:return {'available':False,'actions':[]}
        distance,_,r=min(choices);s=SPECIES[r['species']];state=self.states.get(r['id'],{})
        dead=state.get('dead',False);actions=[]
        for name,a in s['actions'].items():
            if bool(a.get('dead'))!=dead:continue
            tool='item.nature.tool_'+a['tool'] if a['tool'] else ''
            remaining=max(0,state.get('cooldowns',{}).get(name,0)-now)
            in_reach=distance<=(8 if name in {'CATCH','FISH'} else 3.75)
            must_loot=name=='SKIN' and not state.get('looted')
            actions.append({'id':name,'name':a['label'],'tool':tool,'ready':not must_loot and not remaining and (not tool or owned.get(tool,0)>0) and in_reach,
                            'cooldown_s':round(remaining,1),'reason':'Move closer' if not in_reach else
                            'Loot first' if must_loot else 'Recovering' if remaining else 'Need '+a['tool'] if tool and not owned.get(tool,0) else ''})
        if s['domain']!='PLANT' and not dead:
            attack_ready=state.get('attack_after',0)<=now
            actions.append({'id':'ATTACK','name':'Hunt','ready':distance<=3.75 and attack_ready,
                            'reason':'Move closer' if distance>3.75 else 'Recovering' if not attack_ready else ''})
        return {'available':True,'id':r['id'],'species':r['species'],'name':s['name'],'distance_m':round(distance,2),
                'health':state.get('health',s['health']),'max_health':s['health'],'dead':dead,'actions':actions}

    def prepare(self,identity,action,x,y,z,now,owned):
        target=self.target(x,y,z,now,owned,identity)
        if not identity or not target.get('available'):return {'error':'NATURE_TARGET_OUT_OF_REACH'}
        if identity not in self.states and len(self.states)>=MAX_STATES:
            expired=[k for k,v in self.states.items() if max([v.get('respawn_at',0),v.get('hidden_until',0),v.get('calm_until',0),v.get('flee_until',0),*v.get('cooldowns',{}).values()])<=now]
            for k in expired:self.states.pop(k,None)
            if len(self.states)>=MAX_STATES:return {'error':'NATURE_STATE_CAPACITY'}
        a=next((a for a in target['actions'] if a['id']==action),None)
        if not a or not a['ready']:return {'error':'NATURE_ACTION_UNAVAILABLE','message':a.get('reason','') if a else 'Unsupported action'}
        state=dict(self.states.get(identity,{}));state['cooldowns']=dict(state.get('cooldowns',{}))
        s=SPECIES[target['species']]
        if action=='ATTACK':
            state['attack_after']=now+.4
            state['health']=max(0,state.get('health',s['health'])-3)
            state['dead']=state['health']==0;state['respawn_at']=now+300
            row=next(r for r in self.rows if r['id']==identity)
            d=max(.01,math.hypot(row['x']-x,row['z']-z))
            state.update(flee_start=now,flee_until=now+2,flee_dx=(row['x']-x)/d,flee_dz=(row['z']-z)/d)
            table=''
            if state['dead']:state.update(death_x=row['x'],death_y=row['y'],death_z=row['z'],death_at=now)
        else:
            spec=s['actions'][action];table=spec['table_id'] if spec['resource'] else ''
            state['cooldowns'][action]=now+spec['cooldown_s'];state['calm_until']=now+5
            state['flee_until']=now
            row=next(r for r in self.rows if r['id']==identity)
            state.update(calm_x=row['x'],calm_z=row['z'])
            if action=='LOOT':state['looted']=True
            keep_remains=action=='LOOT' and 'SKIN' in s['actions']
            if not keep_remains and (s['domain']=='PLANT' or spec.get('remove') or spec.get('dead')):
                state['hidden_until']=now+spec['cooldown_s']
        cycle=state.get('cycle',0)+1;state['cycle']=cycle
        # Use the full stable identity; Python's salted hash cannot affect loot.
        seed=self.seed
        for c in (identity+action+str(cycle)).encode():seed=((seed^c)*16777619)&0xffffffff
        return {'id':identity,'species':s['id'],'name':s['name'],'action':action,'state':state,'table_id':table,'seed':seed}

    def commit(self,result):
        self.states[result['id']]=result['state'];self._stamp=None
        self.last_result={k:v for k,v in result.items() if k not in {'state','seed'}}

    def save(self,now):
        result={}
        for key,state in self.states.items():
            row=dict(state)
            for field in ('hidden_until','respawn_at','calm_until','flee_until','flee_start','attack_after','death_at'):
                if field in row:row[field]=row[field]-now
            row['cooldowns']={k:v-now for k,v in row.get('cooldowns',{}).items()}
            result[key]=row
        return {'states':result}

    def restore(self,payload,now):
        self.states={};self._stamp=None
        # A restored terrain document can have the same numeric revision as
        # the old one. Cached anchor heights still belong to the old document.
        self.cells.clear()
        self._fixed_revision = None
        self._garden_anchors = self._village_anchors = None
        if not isinstance(payload,dict):return
        states=payload.get('states',{})
        if not isinstance(states,dict):return
        for key,value in list(states.items())[:MAX_STATES]:
            if not isinstance(key,str) or not isinstance(value,dict):continue
            def safe(v,lo,hi):
                try:v=float(v)
                except (TypeError,ValueError,OverflowError):return 0
                return max(lo,min(hi,v)) if math.isfinite(v) else 0
            row={k:safe(v,-20000,20000) for k,v in value.items()
                 if k in {'cycle','health','death_x','death_y','death_z','flee_dx','flee_dz','calm_x','calm_z'}}
            row['dead']=bool(value.get('dead',False));row['cycle']=int(safe(value.get('cycle',0),0,1000000))
            row['looted']=bool(value.get('looted',False))
            if 'health' in value:row['health']=safe(value['health'],0,64)
            for field in ('hidden_until','respawn_at','calm_until','flee_until','flee_start','attack_after','death_at'):
                if field in value:row[field]=now+safe(value[field],-300,3600)
            cooldowns=value.get('cooldowns',{})
            row['cooldowns']={k:now+safe(v,0,3600) for k,v in cooldowns.items() if k in LABELS} if isinstance(cooldowns,dict) else {}
            self.states[key]=row
