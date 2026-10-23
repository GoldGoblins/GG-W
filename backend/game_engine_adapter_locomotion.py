"""One bounded walking planner over actual resident floors and walking hulls.

Routes are geometry observations, not permissions to move. Every consumed edge
is checked again; evicted/replaced pages invalidate the cache. Neither planning
nor movement can mutate the player's safe position or open a native reader.
"""
from __future__ import annotations
from collections import OrderedDict
import heapq,itertools,math,time

STEP=.75
MAX_STEP=.75
MAX_EXPANDED=384
MAX_ROUTE=96
MAX_ROUTES=128


def point(world,x,y,z,*,swimming=False):
    q=world.query(x,y+.65,z)
    height=q.get('height')
    if not q.get('loaded') or q.get('impassable'):return None
    if swimming:
        liquid=world.water_sample(x,y,z);surface=liquid.get('height_m',-100001.)
        if liquid.get('has_surface') is False and liquid.get('body_kind','NONE')!='NONE':return (x,y,z)
        if (type(surface) in (int,float) and math.isfinite(surface) and abs(surface)<=2_000_000
                and liquid.get('has_surface',True) and y<=surface+.35
                and (height is None or surface-height>.8)):
            return (x,float(surface)-.45,z)
    if type(height) not in (int,float) or not math.isfinite(height):return None
    return (x,float(height),z)


def motion(world,start,vertical_speed,dt,*,alive=True):
    """One loaded actor's vertical step; position is feet, never player-safe state."""
    x,y,z=start;q=world.query(x,y+.65,z);floor=q.get('height')
    if not q.get('loaded') or q.get('impassable'):return start,vertical_speed,'HOLD',0.
    if floor is not None and (type(floor) not in (int,float) or not math.isfinite(floor)):
        return start,vertical_speed,'HOLD',0.
    water=world.water_sample(x,y,z);surface=water.get('height_m',-100001.)
    if alive and water.get('has_surface') is False and water.get('body_kind','NONE')!='NONE':
        return start,0.,'SWIM',0.
    if (alive and type(surface) in (int,float) and math.isfinite(surface) and abs(surface)<=2_000_000
            and y<=surface+.35 and (floor is None or surface-floor>.8)):
        target=surface-.45
        return (x,y+max(-1.8*dt,min(1.8*dt,target-y)),z),0.,'SWIM',0.
    if floor is not None and y<=floor+.08:return (x,float(floor),z),0.,'GROUND',0.
    speed=max(-30.,vertical_speed-9.81*dt);next_y=y+speed*dt
    if floor is not None and next_y<=floor:return (x,float(floor),z),0.,'GROUND',max(0.,-speed)
    return (x,next_y,z),speed,'FALL',0.


def edge(world,start,end,*,step=MAX_STEP,swimming=False):
    if not all(type(n) in (int,float) and math.isfinite(n) for p in (start,end) for n in p):return False
    distance=math.hypot(end[0]-start[0],end[2]-start[2])
    if distance>80 or abs(end[1]-start[1])>step:return False
    surfaces=tuple(page.surface for page in world.pages.values())
    if any(not s.line_of_sight((start[0],start[1]+.35,start[2]),(end[0],end[1]+.35,end[2])) for s in surfaces):return False
    steps=max(1,math.ceil(distance/.3))
    height=start[1]
    for i in range(1,steps+1):
        fraction=i/steps;x=start[0]+(end[0]-start[0])*fraction;z=start[2]+(end[2]-start[2])*fraction
        p=point(world,x,height,z,swimming=swimming)
        if p is None or abs(p[1]-height)>step:return False
        corrected=(x,z)
        for s in surfaces:corrected=s.walls(corrected[0],p[1],corrected[1])
        if math.hypot(corrected[0]-x,corrected[1]-z)>.04:return False
        height=p[1]
    return abs(height-end[1])<=step


def _plan_steps(world,start,target,*,max_expanded=MAX_EXPANDED,swimming=False):
    if type(max_expanded) is not int or not 1<=max_expanded<=MAX_EXPANDED:raise ValueError('Walking search capacity invalid')
    if not all(type(n) in (int,float) and math.isfinite(n) for p in (start,target) for n in p):raise ValueError('Walking coordinates invalid')
    origin=point(world,*start,swimming=swimming);goal=point(world,*target,swimming=swimming)
    if origin is None or goal is None:return dict(status='UNLOADED',route=[],expanded=0)
    if math.hypot(goal[0]-origin[0],goal[2]-origin[2])>48:return dict(status='OUT_OF_RANGE',route=[],expanded=0)
    if edge(world,origin,goal,swimming=swimming):return dict(status='READY',route=[goal],expanded=0)
    order=itertools.count();opened=[];first=(0,0,round(origin[1]/.5));positions={first:origin};cost={first:0.};parents={};closed=set()
    heuristic=lambda p:math.hypot(goal[0]-p[0],goal[2]-p[2])
    heapq.heappush(opened,(heuristic(origin),next(order),first));final=None
    minx,maxx=min(origin[0],goal[0])-8,max(origin[0],goal[0])+8
    minz,maxz=min(origin[2],goal[2])-8,max(origin[2],goal[2])+8
    while opened and len(closed)<max_expanded:
        _,_,key=heapq.heappop(opened)
        if key in closed:continue
        closed.add(key);current=positions[key]
        yield len(closed)
        if heuristic(current)<=STEP*1.1 and edge(world,current,goal,swimming=swimming):final=key;break
        for dx,dz in ((0,-1),(1,0),(0,1),(-1,0),(1,-1),(1,1),(-1,1),(-1,-1)):
            nx,nz=origin[0]+(key[0]+dx)*STEP,origin[2]+(key[1]+dz)*STEP
            if not(minx<=nx<=maxx and minz<=nz<=maxz):continue
            candidate=point(world,nx,current[1],nz,swimming=swimming)
            if candidate is None or not edge(world,current,candidate,swimming=swimming):continue
            nk=(key[0]+dx,key[1]+dz,round(candidate[1]/.5))
            if nk in closed:continue
            distance=math.dist(current,candidate);new=cost[key]+distance
            if new>=cost.get(nk,float('inf')):continue
            positions[nk]=candidate;cost[nk]=new;parents[nk]=key
            heapq.heappush(opened,(new+heuristic(candidate),next(order),nk))
    if final is None:return dict(status='CAPACITY' if opened else 'BLOCKED',route=[],expanded=len(closed))
    result=[goal]
    while final!=first:
        result.append(positions[final]);final=parents[final]
        if len(result)>MAX_ROUTE:return dict(status='CAPACITY',route=[],expanded=len(closed))
    result.reverse()
    return dict(status='READY',route=result,expanded=len(closed))


def plan(world,start,target,*,max_expanded=MAX_EXPANDED,swimming=False):
    search=_plan_steps(world,start,target,max_expanded=max_expanded,swimming=swimming)
    while True:
        try:next(search)
        except StopIteration as done:return done.value


class WalkingRoutes:
    def __init__(self,world):
        self.world=world;self.rows=OrderedDict();self.plans=0;self.last_status='IDLE';self.stamp=None
        self.budget_time=None;self.expansion_budget=MAX_EXPANDED;self.search_budget=2;self.deadline=0.
    def waypoint(self,identity,start,target,now,*,swimming=False):
        world=self.world
        if now!=self.budget_time:
            self.budget_time=now;self.expansion_budget=MAX_EXPANDED;self.search_budget=2;self.deadline=time.perf_counter()+.008
        identity=(identity,swimming)
        stamp=(getattr(world,'revision',0),tuple((key,id(page.surface),None if page.surface.active_props is None else frozenset(page.surface.active_props)) for key,page in world.pages.items()))
        if stamp!=self.stamp:self.rows.clear();self.stamp=stamp
        goal=point(world,*target,swimming=swimming)
        if goal is None:self.last_status='UNLOADED';return start
        if time.perf_counter()>=self.deadline:self.last_status='DEFERRED';return start
        if edge(world,start,goal,swimming=swimming):self.rows.pop(identity,None);self.last_status='DIRECT';return goal
        cached=self.rows.get(identity)
        if cached and (math.dist(cached['target'],goal)>=STEP or now-cached['time']>=1.):
            cached=None;self.rows.pop(identity,None)
        if cached:
            route=cached['route']
            while route and math.hypot(route[0][0]-start[0],route[0][2]-start[2])<.2:route.pop(0)
            if route and edge(world,start,route[0],swimming=swimming):self.rows.move_to_end(identity);return route[0]
            if not route and 'search' not in cached and now-cached['time']<.35:return start
        if self.expansion_budget<1 or self.search_budget<1:self.last_status='DEFERRED';return start
        if not cached or 'search' not in cached:
            cached=dict(target=goal,time=now,route=[],search=_plan_steps(world,start,goal,swimming=swimming),expanded=0)
            self.rows[identity]=cached;self.plans+=1
        self.search_budget-=1;cached['time']=now;result=None
        while self.expansion_budget>0 and time.perf_counter()<self.deadline:
            try:
                expanded=next(cached['search'])
                self.expansion_budget-=expanded-cached['expanded'];cached['expanded']=expanded
            except StopIteration as done:result=done.value;break
        if result is not None:
            cached.pop('search',None);cached['route']=result['route'];self.last_status=result['status']
        else:self.last_status='DEFERRED'
        self.rows.move_to_end(identity)
        while len(self.rows)>MAX_ROUTES:self.rows.popitem(last=False)
        return cached['route'][0] if cached['route'] else start


def routes(world):
    result=getattr(world,'_walking_routes',None)
    if result is None:result=WalkingRoutes(world);world._walking_routes=result
    return result


def move(world,start,x,z,*,swimming=False):
    destination=point(world,x,start[1],z,swimming=swimming)
    if destination is None or not edge(world,start,destination,swimming=swimming):return start
    return destination
