"""Camera-driven WMO portal rectangles over original MOPV/MOPT/MOPR.

Equations, side/on-plane gates and three passes follow GgEngine's
engine-world/src/wmo_portal/mod.rs. This implementation uses Qt world axes
and a perspective camera, without pulling the Bevy renderer into the client.
"""
import math,time

FULL=(-1.,-1.,1.,1.)
def dot(a,b):return sum(x*y for x,y in zip(a,b))
def cross(a,b):return (a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])
def normal(v):
    length=math.sqrt(dot(v,v))
    if length<1e-8:raise ValueError('Degenerate world camera basis')
    return tuple(x/length for x in v)

class PortalCamera:
    def __init__(self,view):
        def vector(key):
            p=view.get(key)
            if not isinstance(p,(tuple,list)) or len(p)!=3 or any(isinstance(n,bool) or not isinstance(n,(float,int)) or not math.isfinite(n) or abs(n)>2_000_000 for n in p):raise ValueError('Invalid world camera vector')
            return tuple(p)
        self.eye=vector('eye');self.forward=normal(vector('forward'));self.right=normal(cross(self.forward,vector('up')));self.up=cross(self.right,self.forward)
        def number(key,low,high):
            n=view.get(key)
            if isinstance(n,bool) or not isinstance(n,(float,int)) or not math.isfinite(n) or not low<=n<=high:raise ValueError('Invalid world camera projection')
            return float(n)
        self.aspect=number('aspect',.05,20);self.tan=math.tan(math.radians(number('fov',1,179))*.5)
        self.near=number('near',.001,10000);self.far=number('far',.002,2_000_000)
        if self.far<=self.near:raise ValueError('Invalid world camera clip span')
    def clip(self,p):
        delta=tuple(p[i]-self.eye[i] for i in range(3));depth=dot(delta,self.forward)
        return (dot(delta,self.right)/(self.tan*self.aspect),dot(delta,self.up)/self.tan,depth,depth)
    def box_visible(self,corners,rect=FULL):
        if not corners:return True
        points=[self.clip(p) for p in corners]
        tests=(lambda p:p[0]-rect[0]*p[3],lambda p:rect[2]*p[3]-p[0],lambda p:p[1]-rect[1]*p[3],lambda p:rect[3]*p[3]-p[1],lambda p:p[3]-self.near,lambda p:self.far-p[3])
        return all(any(test(p)>=0 for p in points) for test in tests)

def intersect(a,b):
    rect=(max(a[0],b[0]),max(a[1],b[1]),min(a[2],b[2]),min(a[3],b[3]))
    return rect if rect[2]-rect[0]>=.001 and rect[3]-rect[1]>=.001 else None

def clip_sides(points):
    for axis,sign in ((0,1),(0,-1),(1,1),(1,-1)):
        result=[]
        for i,a in enumerate(points):
            b=points[(i+1)%len(points)];da=a[3]+sign*a[axis];db=b[3]+sign*b[axis]
            if da>=0:result.append(a)
            if (da>=0)!=(db>=0):
                t=da/(da-db);result.append(tuple(a[k]+(b[k]-a[k])*t for k in range(4)))
        points=result
        if len(points)<3:return []
    return points

def on_portal(info,eye):
    plane=info['plane']
    if abs(dot(plane[:3],eye)+plane[3])>.01:return False
    axes=[i for i in range(3) if i!=max(range(3),key=lambda k:abs(plane[k]))];u,v=axes
    points=info['points'];inside=False
    for i,a in enumerate(points):
        b=points[(i+1)%len(points)]
        # The authored boundary is inside, too; avoids a one-frame slit.
        dx,dy=b[u]-a[u],b[v]-a[v];px,py=eye[u]-a[u],eye[v]-a[v]
        if abs(dx*py-dy*px)<1e-7 and min(a[u],b[u])-1e-7<=eye[u]<=max(a[u],b[u])+1e-7 and min(a[v],b[v])-1e-7<=eye[v]<=max(a[v],b[v])+1e-7:return True
        if (a[v]>eye[v])!=(b[v]>eye[v]) and eye[u]<(b[u]-a[u])*(eye[v]-a[v])/(b[v]-a[v])+a[u]:inside=not inside
    return inside

def portal_rect(info,camera):
    if on_portal(info,camera.eye):return FULL
    points=clip_sides([camera.clip(p) for p in info['points']])
    if not points:return None
    ndc=[(p[0]/(1e-5 if abs(p[3])<.001 else p[3]),p[1]/(1e-5 if abs(p[3])<.001 else p[3])) for p in points]
    return (min(p[0] for p in ndc),min(p[1] for p in ndc),max(p[0] for p in ndc),max(p[1] for p in ndc))

def connected(groups,refs,room):
    if room is None:return set(range(len(groups)))
    visible={room};todo=[room]
    while todo:
        group=groups[todo.pop()];start=group['portal_start'];count=group['portal_count']
        for ref in refs[start:start+count]:
            other=ref['group']
            if 0<=other<len(groups) and other not in visible:visible.add(other);todo.append(other)
    return visible

def visibility(metadata,camera,room,seeds=()):
    groups=metadata['groups'];portals=metadata['portals'] or {};refs=portals.get('refs',[]);infos=portals.get('infos',[])
    if camera is None or not infos:return connected(groups,refs,room),{'mode':'CONNECTIVITY_NO_CAMERA' if camera is None else 'CONNECTIVITY_MISSING_GEOMETRY','iterations':0,'windows':0,'fogged':list(range(len(groups))) if room is not None else []}
    visible=set();fogged=set();windows=[];pushed=set();iterations=0;edges=0;deadline=time.perf_counter()+.012
    def walk(stack,record):
        nonlocal iterations,edges
        while stack:
            iterations+=1
            if iterations>4096:
                # A pathological graph must neither stall the GUI nor hide the
                # surrounding world. This conservative fallback is reported.
                return False
            gi,came,rect,depth,chain=stack.pop()
            if not 0<=gi<len(groups):continue
            visible.add(gi);group=groups[gi];flags=group.get('flags',0)
            if chain and flags&0x48==0:fogged.add(gi)
            if depth>=10:continue
            start=group['portal_start'];count=group['portal_count']
            for ref in refs[start:start+count]:
                edges+=1
                if edges>4096 or (edges%64==0 and time.perf_counter()>deadline):return False
                other=ref['group'];portal=ref['portal']
                if other==came or not 0<=other<len(groups) or not 0<=portal<len(infos):continue
                info=infos[portal];distance=dot(info['plane'][:3],camera.eye)+info['plane'][3]
                if (distance if ref['side']>=0 else -distance)<0:continue
                projected=portal_rect(info,camera);narrow=intersect(rect,projected) if projected else None
                if narrow is None:continue
                if record and groups[other].get('flags',0)&8 and portal not in pushed:
                    pushed.add(portal);windows.append(narrow)
                    if len(windows)>16:return False
                stack.append((other,gi,narrow,depth+1,chain and flags&0x48==0))
                if len(stack)>4096:return False
        return True
    stack=[(root,-1,FULL,0,True) for root in (seeds or (room,))] if room is not None else [(i,-1,FULL,0,False) for i,g in enumerate(groups) if g.get('flags',0)&8]
    valid=walk(stack,room is not None)
    if valid:
        for rect in windows:
            roots=[(i,-1,rect,0,False) for i,g in enumerate(groups) if g.get('flags',0)&0x10008==8 and camera.box_visible(g.get('corners'),rect)]
            if not walk(roots,False):valid=False;break
    if valid:
        visible.update(i for i,g in enumerate(groups) if g.get('flags',0)&0x10000 and camera.box_visible(g.get('corners')))
    else:visible=set(range(len(groups)))
    return visible,{'mode':'PORTAL_RECTANGLES' if valid else 'BOUNDED_FALLBACK','iterations':iterations,'windows':len(windows),'window_rects':windows,'fogged':sorted(fogged)}
