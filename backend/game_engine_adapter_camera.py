"""Camera arm over the resident original camera/LOS hulls and wet-cell mesh.

The sweep is continuous (faces, edges and vertices), two-sided, and ignores
origin penetration. The 0.3 probe, water ray and snap-in/6-per-second return
follow engine-world/collision.rs and engine-app/player/camera*.rs. This is
the GG orbit camera adapter, not the original remote-view/ride state graph.
"""
from __future__ import annotations
import math

RADIUS=.3
MAX_TRIANGLES=8192
MAX_ARM=256.

def sub(a,b):return tuple(a[i]-b[i] for i in range(3))
def add(a,b):return tuple(a[i]+b[i] for i in range(3))
def mul(a,n):return tuple(v*n for v in a)
def dot(a,b):return a[0]*b[0]+a[1]*b[1]+a[2]*b[2]
def cross(a,b):return (a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])

def inside(p,a,b,c):
    ab,ac,ap=sub(b,a),sub(c,a),sub(p,a)
    aa,cc,bc=dot(ab,ab),dot(ac,ac),dot(ab,ac);d=aa*cc-bc*bc
    if d<=1e-18:return False
    u=(cc*dot(ap,ab)-bc*dot(ap,ac))/d;v=(aa*dot(ap,ac)-bc*dot(ap,ab))/d
    return u>=-1e-8 and v>=-1e-8 and u+v<=1+1e-8

def edge_distance(p,a,b):
    edge=sub(b,a);length=dot(edge,edge)
    t=max(0.,min(1.,dot(sub(p,a),edge)/length)) if length>1e-18 else 0.
    d=sub(p,add(a,mul(edge,t)));return dot(d,d)

def distance_squared(p,a,b,c):
    n=cross(sub(b,a),sub(c,a));nn=dot(n,n)
    if nn>1e-18:
        offset=dot(sub(p,a),n)/nn
        if inside(sub(p,mul(n,offset)),a,b,c):return offset*offset*nn
    return min(edge_distance(p,a,b),edge_distance(p,b,c),edge_distance(p,c,a))

def roots(a,b,c):
    """Entry/exit fractions, with a stable quadratic for grazing edges."""
    if a<=1e-18:return ()
    discriminant=b*b-a*c
    if discriminant < -1e-12*max(1.,b*b,abs(a*c)):return ()
    root=math.sqrt(max(0.,discriminant));q=-b-math.copysign(root,b)
    if abs(q)<1e-18:return (-b/a,)
    return tuple(sorted((q/a,c/q)))

def sphere_triangle(start,end,a,b,c,radius=RADIUS):
    """First contact fraction with a triangle, including its rounded rim."""
    if distance_squared(start,a,b,c)<=radius*radius+1e-10:return None
    move=sub(end,start);hits=[];n=cross(sub(b,a),sub(c,a));nn=dot(n,n)
    if nn>1e-18:
        n=mul(n,1/math.sqrt(nn));offset=dot(sub(start,a),n);speed=dot(move,n)
        if abs(speed)>1e-12:
            for side in (-radius,radius):
                t=(side-offset)/speed
                if 0<=t<=1 and inside(sub(add(start,mul(move,t)),mul(n,side)),a,b,c):hits.append(t)
    for p,q in ((a,b),(b,c),(c,a)):
        edge=sub(q,p);ee=dot(edge,edge)
        if ee<=1e-18:continue
        rel=sub(start,p);u=dot(rel,edge)/ee;du=dot(move,edge)/ee
        radial=sub(rel,mul(edge,u));velocity=sub(move,mul(edge,du))
        for t in roots(dot(velocity,velocity),dot(radial,velocity),dot(radial,radial)-radius*radius):
            if 0<=t<=1 and 0<=u+du*t<=1:hits.append(t)
    vv=dot(move,move)
    for p in (a,b,c):
        rel=sub(start,p)
        hits.extend(t for t in roots(vv,dot(rel,move),dot(rel,rel)-radius*radius) if 0<=t<=1)
    return min(hits,default=None)

def triangle_ray(start,end,a,b,c):
    move=sub(end,start);ab,ac=sub(b,a),sub(c,a);h=cross(move,ac);det=dot(ab,h)
    if abs(det)<1e-12:return None
    s=sub(start,a);u=dot(s,h)/det
    if u<0 or u>1:return None
    q=cross(s,ab);v=dot(move,q)/det
    if v<0 or u+v>1:return None
    t=dot(ac,q)/det;return t if 0<=t<=1 else None

def cells(start,end,size,radius=0.):
    # Supercover DDA: sampling a diagonal misses short visits near grid corners.
    x,z=math.floor(start[0]/size),math.floor(start[2]/size);visited={(x,z)}
    dx,dz=end[0]-start[0],end[2]-start[2];sx=1 if dx>0 else -1;sz=1 if dz>0 else -1
    tx=(((x+1)*size if sx>0 else x*size)-start[0])/dx if dx else math.inf
    tz=(((z+1)*size if sz>0 else z*size)-start[2])/dz if dz else math.inf
    stepx=size/abs(dx) if dx else math.inf;stepz=size/abs(dz) if dz else math.inf
    while min(tx,tz)<=1:
        if tx==tz:
            visited.update(((x+sx,z),(x,z+sz)));x+=sx;z+=sz;tx+=stepx;tz+=stepz
        elif tx<tz:x+=sx;tx+=stepx
        else:z+=sz;tz+=stepz
        visited.add((x,z))
    margin=math.ceil(radius/size)
    out={(cx+ox,cz+oz) for cx,cz in visited for ox in range(-margin,margin+1) for oz in range(-margin,margin+1)}
    return sorted(out)

def cast(pages,start,end,liquid=True):
    """Shared query cap across pages; overflow clips safely at the origin."""
    move=sub(end,start);length=math.sqrt(dot(move,move))
    if length>MAX_ARM:raise ValueError('Camera arm capacity exceeded')
    best=None;seen=set();tested=0;solid_cells=cells(start,end,8,RADIUS)
    def count(key):
        nonlocal tested
        if key in seen:return False
        seen.add(key);tested+=1
        if tested>MAX_TRIANGLES:raise OverflowError
        return True
    try:
        for page in pages:
            for cell in solid_cells:
                for triangle in page.sight.cells.get(cell,()):
                    a,b,c,row=triangle
                    if not page.sight.enabled(row) or not count(('solid',id(triangle))):continue
                    if any(max(start[k],end[k])+RADIUS<min(a[k],b[k],c[k]) or
                           min(start[k],end[k])-RADIUS>max(a[k],b[k],c[k]) for k in range(3)):continue
                    hit=sphere_triangle(start,end,a,b,c)
                    if hit is not None and (best is None or hit<best):best=hit
            if not liquid:continue
            grids={id(grid):grid for cell in cells(start,end,16) for grid in page.liquids.cells.get(cell,())}
            for grid in grids.values():
                indices=grid.row['indices']
                for i in range(0,len(indices),3):
                    if not count(('water',id(grid),i)):continue
                    a,b,c=(grid.points[n] for n in indices[i:i+3])
                    if any(max(start[k],end[k])<min(a[k],b[k],c[k]) or
                           min(start[k],end[k])>max(a[k],b[k],c[k]) for k in range(3)):continue
                    hit=triangle_ray(start,end,a,b,c)
                    if hit is not None and (best is None or hit<best):best=hit
    except OverflowError:return 0.,tested,True
    return best*length if best is not None else None,tested,False

def corridor(surface,feet,target,live):
    """Original water band ties, floor/cap and unit headroom."""
    floor=5/6;cap=live;band='CLEAR'
    if surface is not None:
        depth=surface-feet;excess=depth-target
        if excess<2/9:band='SURFACE';floor=depth+2/9;cap=max(live,floor)
        elif excess<5/9:band='SUBMERGE';cap=max(depth-5/6,5/6)
    return min(floor+max(max(target,live)-floor,1/9),cap),floor,band

class CameraBoom:
    def __init__(self):self.reset()
    def reset(self):self.distance=None;self.last=None;self.frames=0;self.status={}
    def solve(self,pages,head,seat,delta,liquid):
        move=sub(seat,head);length=math.sqrt(dot(move,move))
        hit,triangles,overflow=cast(pages,head,seat,liquid);open_distance=length if hit is None else hit
        # A teleport starts a fresh arm instead of carrying a near-wall result
        # to an unrelated room. Local movement preserves the settled distance.
        if self.distance is None or self.last is not None and math.dist(head,self.last)>8:self.distance=open_distance
        elif open_distance<self.distance:self.distance=open_distance
        else:self.distance+=(open_distance-self.distance)*-math.expm1(-6*delta)
        self.last=head;self.frames+=1
        self.status={'clipped':hit is not None,'distance':self.distance,'open_distance':open_distance,
                     'requested_distance':length,'triangles':triangles,'overflow':overflow,'frames':self.frames}
        return add(head,mul(move,min(1.,self.distance/length))) if length>1e-12 else seat

def number(value,limit):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or abs(value)>limit:raise ValueError('Invalid camera value')
    return float(value)

def solve(stream,view):
    if not isinstance(view,dict):raise ValueError('Camera view must be an object')
    feet=view.get('feet')
    if not isinstance(feet,(list,tuple)) or len(feet)!=3:raise ValueError('Camera feet must have three values')
    feet=tuple(number(n,2_000_000) for n in feet)
    height=number(view.get('head_height',1.4),32);pivot=number(view.get('pivot_height',1.45),32)
    distance=number(view.get('distance',6),MAX_ARM);delta=number(view.get('delta',0),1)
    yaw=math.radians(number(view.get('yaw',0),360_000));pitch=math.radians(number(view.get('pitch',0),89))
    liquid=view.get('water_collision',True)
    if height<0 or pivot<0 or distance<0 or delta<0 or not isinstance(liquid,bool):raise ValueError('Invalid camera dimensions/options')
    band='CLEAR';floor=5/6
    if liquid:
        water=stream.water_sample(*feet)
        surface=water['height_m'] if water['body_kind']!='NONE' and water['has_surface'] else None
        pivot,floor,band=corridor(surface,feet[1],pivot,pivot)
    head=add(feet,(0.,max(height,floor),0.))
    seat=add(feet,(math.sin(yaw)*math.cos(pitch)*distance,pivot-math.sin(pitch)*distance,math.cos(yaw)*math.cos(pitch)*distance))
    point=stream.camera_boom.solve(tuple(stream.pages.values()),head,seat,delta,liquid)
    stream.camera_boom.status['water_band']=band
    return point
