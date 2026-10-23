"""Offline caricature profiles shared by authored and native meshes.

Changes local geometry only. No camera, clock, placement or simulation input.
The same continuous mapping is used for attached parts and their normals.
"""
import math,struct
STYLE='GG_PS2_CARICATURE_R1'

def smooth(a,b,v):
    t=max(0,min(1,(v-a)/(b-a)));return t*t*(3-2*t)

def limits(points):return tuple([f(p[i] for p in points) for i in range(3)] for f in (min,max))

def _base_point(p,family,variant,bounds):
    low,high=bounds;span=[max(high[i]-low[i],.001) for i in range(3)]
    cx=(low[0]+high[0])/2;cz=(low[2]+high[2])/2;h=span[1]
    px,y,pz=map(float,p);x=px-cx;z=pz-cz;t=max(0,min(1,(y-low[1])/h))
    v=int(variant)%4;sign=(1,-1,1,-1)[v];phase=(0,.55,1.2,-.8)[v]
    if family=='character':
        head=smooth(.68,.83,t);foot=1-smooth(.09,.20,t)
        return cx+x*(1+(.17+.025*v)*head+.10*foot),y+h*.025*head,cz+z*(1+.15*head+.12*foot)
    if family=='animal':
        face=smooth(.56,.82,(pz-low[2])/span[2])
        return cx+x*(1+(.22+.025*v)*face),y+h*.055*face*smooth(.18,.42,t),pz+span[2]*(.065+.012*v)*face
    if family=='plant':
        mass=smooth(.20,.65,t)
        return cx+x*(1.22+.07*v)+h*.18*sign*math.sin(math.pi*t),y,cz+z*(1.18+.04*v)+h*.10*math.sin(math.pi*t+phase)*mass
    if family=='weapon':
        blade=smooth(.30,.62,t)
        return cx+x*(1.25+.10*v)+h*(.045+.015*v)*sign*math.sin(math.pi*t)*blade,y,cz+z*1.20
    if family=='equipment':
        return cx+x*(1.12+.035*v),y+h*.06*math.sin(math.pi*t)*max(-.5,min(.5,x/span[0]))*sign,cz+z*(1.12+.025*v)
    if family=='cloud':
        return cx+x*(1.12+.06*v),low[1]+h*(t*.82+.10*math.sin(math.pi*t+phase)),cz+z*(1.18+.04*v)
    if family=='lantern':
        head=smooth(.70,.85,t)
        return cx+x*(1+(.40+.07*v)*head)+h*(.12+.025*v)*sign*math.sin(math.pi*t)*(1-smooth(.60,.80,t)),y,cz+z*(1+(.30+.035*v)*head)
    if family=='cottage':
        # Change overhangs and chimney, retaining the roof above the walkable
        # footprint exactly; the existing floor/door collision remains valid.
        roof=smooth(.54,.65,t)
        edge=max(smooth(.71,.89,abs(x)/(span[0]*.5)),smooth(.74,.90,abs(z)/(span[2]*.5)))
        chimney=smooth(.74,.84,t) if px>2.3 else 0
        return px+sign*(.12*v*edge*roof+.12*v*chimney),y+.10*v*edge*roof,pz+sign*.07*v*chimney
    if family=='architecture':
        top=smooth(.60,.90,t)
        return cx+x*(1+(.18+.025*v)*top)+h*(.065+.012*v)*sign*top,y-h*(.065+.012*v)*top*math.sin(math.pi*(x/span[0]+.5))**2,cz+z*(1+(.11+.025*v)*top)
    return cx+x*(1+.22*math.sin(math.pi*t)+.07*v)+h*.10*sign*t*t,y,cz+z*(1+.16*math.sin(math.pi*t)+.025*v)

def point(p,family,variant,bounds):
    v=int(variant)%36
    q=_base_point(p,family,v%4,bounds)
    if v<4:return q
    kind,detail=divmod(v,6);low,high=bounds
    h=max(.001,high[1]-low[1]);w=max(.001,high[0]-low[0]);depth=max(.001,high[2]-low[2])
    cx=(low[0]+high[0])/2;cz=(low[2]+high[2])/2
    x,y,z=q;t=max(0,min(1,(p[1]-low[1])/h));u=(p[0]-cx)/w
    side=(-1,1,-1,1,1,-1)[detail];shoulder=smooth(.42,.59,t)*(1-smooth(.68,.79,t));head=smooth(.72,.86,t)
    if family=='character':
        width=(1.13,.90,1.25,.85,1.03,.95)[kind]
        breadth=1+(width-1)*shoulder+(.04*detail-.10)*head
        return cx+(x-cx)*breadth,y+h*(.013*detail-.028)*head,cz+(z-cz)*(1+(width-1)*shoulder+.10*head*math.sin(v))
    if family=='cottage':
        # Floors and the collision roof inside the walkable footprint stay put.
        edge=max(smooth(.75,.92,abs((p[0]-cx)/w)*2),smooth(.75,.92,abs((p[2]-cz)/depth)*2));roof=smooth(.56,.72,t)
        return x+h*.025*side*edge*roof,y+h*(.018*kind-.035)*edge*roof,z+depth*.028*math.sin(v)*edge*roof
    if family=='architecture':
        top=smooth(.55,.83,t);curve=(.11,-.07,.05,-.12,.09,-.03)[kind]
        return cx+(x-cx)*(1+(.08*detail-.18)*top)+h*curve*top,y+h*.05*math.sin(u*math.pi+detail)*top,cz+(z-cz)*(1+(.10*kind-.20)*top)
    if family=='weapon':
        blade=smooth(.25,.6,t);bends=(.13,-.11,.05,.18,-.04,.09)
        return cx+(x-cx)*(1+.12*detail*blade)+h*bends[kind]*math.sin(math.pi*t)*blade,y,cz+(z-cz)*(1+.10*kind*blade)
    if family=='equipment':
        return cx+(x-cx)*(1+(.09*kind-.14)*math.sin(math.pi*t)),y+h*.055*side*math.sin(math.pi*t)*u,cz+(z-cz)*(1+.075*detail*math.sin(math.pi*t))
    if family=='cloud':
        return cx+(x-cx)*(1+.15*kind),low[1]+(y-low[1])*(.61+.13*detail)+h*.22*math.sin(u*math.pi+kind),cz+(z-cz)*(.80+.17*detail)
    if family=='lantern':
        top=smooth(.66,.85,t)
        return cx+(x-cx)*(1+.16*kind*top)+h*.055*detail*side*math.sin(math.pi*t),y,cz+(z-cz)*(1+.12*detail*top)
    return cx+(x-cx)*(1+.08*kind)+h*.04*detail*side*math.sin(math.pi*t),y,cz+(z-cz)*(1+.055*detail)

def deform(points,family,variant=0,bounds=None):
    bounds=bounds if bounds is not None else limits(points)
    return [point(p,family,variant,bounds) for p in points]

def deform_normals(points,normals,family,variant=0,bounds=None):
    bounds=bounds if bounds is not None else limits(points)
    delta=max(.00001,max(bounds[1][i]-bounds[0][i] for i in range(3))*.00001)
    def cross(a,b):return (a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])
    out=[]
    for p,n in zip(points,normals):
        columns=[]
        for axis in range(3):
            a=list(p);b=list(p);a[axis]+=delta;b[axis]-=delta
            a=point(a,family,variant,bounds);b=point(b,family,variant,bounds)
            columns.append([(a[i]-b[i])/(2*delta) for i in range(3)])
        a,b,c=columns;cofactors=(cross(b,c),cross(c,a),cross(a,b))
        transformed=[sum(n[j]*cofactors[j][i] for j in range(3)) for i in range(3)]
        length=math.sqrt(sum(v*v for v in transformed)) or 1
        out.append(tuple(v/length for v in transformed))
    return out

def compiled(vertices,family,variant=0,bounds=None):
    rows=list(struct.iter_unpack('<10f',vertices))
    if not rows:return bytearray(vertices)
    positions=[r[:3] for r in rows];normals=[r[3:6] for r in rows]
    bounds=bounds if bounds is not None else limits(positions)
    shaped=deform(positions,family,variant,bounds);normal=deform_normals(positions,normals,family,variant,bounds)
    return bytearray(b''.join(struct.pack('<10f',*p,*n,*r[6:]) for p,n,r in zip(shaped,normal,rows)))
