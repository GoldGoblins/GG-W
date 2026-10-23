"""Original architecture shapes; offline meshes keep the saved wall/door footprint."""
import math
import struct
from functools import lru_cache
from pathlib import Path

PLASTER=(.74,.60,.39,1)
STONE=(.46,.42,.34,1)
WOOD=(.32,.17,.08,1)
WOOD_EDGE=(.50,.29,.14,1)
ROOF=(.63,.23,.105,1)
WINDOW=(.12,.24,.23,1)
RIDGE_X=.85
EAVE_X=6.1

def cottage_roof_y(x,z=0):
    span=EAVE_X-RIDGE_X if x>=RIDGE_X else EAVE_X+RIDGE_X
    t=min(1,abs(x-RIDGE_X)/span)
    # A heavy, scooped hat with curled eaves and lifted ridge ends. The same
    # profile is sampled by roof collision, including its longitudinal bend.
    return 8-3.9*t**.85+.9*t**5+.45*min(1,abs(z)/4.5)**3*(1-t)**2

@lru_cache(maxsize=1)
def _ground_paint():
    # Only the offline road compiler uses this. The game reads .ggmesh files.
    path=Path(__file__).resolve().parents[1]/'qml/assets/authored/world/textures/gg-ashbell-ground-wash.png'
    if not path.exists():return None
    from PIL import Image
    return Image.open(path).convert('RGB')

def road_color(x,z,edge):
    wash=.92+.055*math.sin(x*.83+math.sin(z*.49))+.025*math.sin(z*2.3+x*1.4)
    color=(.48*wash,.34*wash,.20*wash)
    distance=max(abs(x+7398),abs(z-248))
    if edge>.99 and distance<316:
        image=_ground_paint()
        if image is not None:
            u=round((x+7398+320)/640*(image.width-1));v=round((z-248+320)/640*(image.height-1))
            pixel=image.getpixel((u,v))
            grass=tuple(base*(channel/255)**2.2 for base,channel in zip((.29,.43,.16),pixel))
            t=max(0,min(1,(distance-260)/56));fade=1-t*t*(3-2*t)
            color=tuple(a*(1-fade)+b*fade for a,b in zip(color,grass))
    return (*color,1)

def quad(mesh,points,color):
    mesh.triangle(points[0],points[1],points[2],color)
    mesh.triangle(points[0],points[2],points[3],color)

def round_window(mesh,x,z):
    """A broad octagonal carved frame, with glass inside its own silhouette."""
    front=z+math.copysign(.09,z)
    for i in range(8):
        a=2*math.pi*i/8;b=2*math.pi*(i+1)/8
        def point(angle,rx,ry,depth):return (x+rx*math.cos(angle),3.1+ry*math.sin(angle),depth)
        quad(mesh,[point(a,1.,1.12,z),point(b,1.,1.12,z),
                   point(b,.72,.83,front),point(a,.72,.83,front)],WOOD_EDGE)
        mesh.triangle((x,3.1,front),point(a,.72,.83,front),point(b,.72,.83,front),WINDOW)
    mesh.box((x,2.03,z),(2.1,.25,.42),WOOD_EDGE)

def carved_post(mesh,x,z):
    """Three broad segments give the timber a slight authored outward bow."""
    for i in range(3):
        y0=i*5.1/3;y1=(i+1)*5.1/3
        def center(y):return (x+math.copysign(.18*math.sin(math.pi*y/5.1),x),y,z)
        mesh.beam(center(y0),center(y1),.65,WOOD)

def cottage(mesh,lod):
    """Thick eaves, bowed roof, timber frame and stone footing in three LODs.

    The walls and traversable opening retain the original coordinates. Roof
    centre and eave heights retain the existing collision envelope.
    """
    detail=lod==0;mid=lod<2
    if detail:
        mesh.box((0,.15,0),(9,.3,7),STONE)
        for x in (-4.35,4.35):mesh.box((x,2.5,0),(.3,5,7),PLASTER)
        mesh.box((0,2.5,3.35),(9,5,.3),PLASTER)
        for x in (-2.8,2.8):mesh.box((x,2.5,-3.35),(3.3,5,.3),PLASTER)
        mesh.box((0,4.5,-3.35),(2.3,1,.3),WOOD)
    else:mesh.box((0,2.5,0),(9,5,7),PLASTER)
    # The roof rises above a deep dark eave, with broad curved panels rather
    # than an infinitely thin pair of uniform triangles.
    slices=8 if detail else 5 if mid else 3
    rows=3 if detail else 1
    roof_y=cottage_roof_y
    for side in (-1,1):
        for i in range(slices):
            span=EAVE_X-RIDGE_X if side==1 else EAVE_X+RIDGE_X
            x0=RIDGE_X+side*span*i/slices;x1=RIDGE_X+side*span*(i+1)/slices
            for j in range(rows):
                z0=-4.5+9*j/rows;z1=-4.5+9*(j+1)/rows
                shade=.86+.13*math.sin(i*2.7+j*1.8)**2
                color=tuple(c*shade for c in ROOF[:3])+(1,)
                pts=[(x0,roof_y(x0,z0),z0),(x0,roof_y(x0,z1),z1),(x1,roof_y(x1,z1),z1),(x1,roof_y(x1,z0),z0)]
                quad(mesh,pts if side==1 else pts[::-1],color)
            for z in (-4.5,4.5):
                mesh.beam((x0,roof_y(x0,z)-.12,z),(x1,roof_y(x1,z)-.12,z),.62,WOOD_EDGE)
        mesh.box((side*(EAVE_X-.05),4.86,0),(.48,.44,9.4),WOOD)
    # Close the triangular ends without closing the walkable house door.
    for z in (-4.35,4.35):
        for side in (-1,1):
            span=EAVE_X-RIDGE_X if side==1 else EAVE_X+RIDGE_X
            for i in range(slices):
                x0=RIDGE_X+side*span*i/slices;x1=RIDGE_X+side*span*(i+1)/slices
                pts=[(x0,4.68,z),(x1,4.68,z),(x1,roof_y(x1,z),z),(x0,roof_y(x0,z),z)]
                quad(mesh,pts if (z>0)==(side>0) else pts[::-1],PLASTER)
    for z0,z1 in ((-4.6,-2.3),(-2.3,0),(0,2.3),(2.3,4.6)):
        mesh.beam((RIDGE_X,roof_y(RIDGE_X,z0),z0),(RIDGE_X,roof_y(RIDGE_X,z1),z1),.65,WOOD_EDGE)
    # Chunky, crooked chimney with an oversized lip, rather than a thin box.
    loops=[[(cx+sx*r,y,1+sz*r) for sx,sz in ((-1,-1),(1,-1),(1,1),(-1,1))]
           for cx,y,r in ((3,4,.85),(3.2,6.1,.66),(3.65,8.05,.78))]
    for lower,upper in zip(loops,loops[1:]):
        for i in range(4):quad(mesh,[lower[i],lower[(i+1)%4],upper[(i+1)%4],upper[i]],STONE)
    mesh.box((3.65,8.05,1),(2.25,.5,2.25),WOOD_EDGE)
    if mid:
        for x in (-4.38,4.38):
            for z in (-3.42,3.42):carved_post(mesh,x,z)
        for z in (-3.56,3.56):
            if z<0:
                for x in (-2.8,2.8):mesh.box((x,.58,z),(3.3,.8,.22),STONE)
            else:mesh.box((0,.58,z),(9,.8,.22),STONE)
            mesh.box((0,4.65,z),(9,.48,.42),WOOD)
            for x in (-3,3):
                if detail:round_window(mesh,x,z)
                else:
                    mesh.box((x,3.1,z),(2.,2.24,.18),WOOD_EDGE)
                    mesh.box((x,3.1,z+math.copysign(.12,z)),(1.44,1.66,.13),WINDOW)
        if not detail:mesh.box((0,1.8,-3.56),(1.6,3.6,.15),WOOD)
    if detail:
        # Rear frame and side braces carry their own silhouette and contact.
        for x in (-1.35,1.35):mesh.box((x,1.9,-3.54),(.35,3.8,.25),WOOD_EDGE)
        mesh.box((0,3.83,-3.54),(3.1,.35,.25),WOOD_EDGE)
        # Quiet plaster panels and broad carved corners replace the fine
        # cross-braced medieval timber grid that dominated the old facade.
        mesh.box((0,.28,-4.3),(3.5,.56,1.5),STONE)
        # Small stone seams at the base and chimney, not a noisy entire wall.
        for z in (-3.7,3.7):
            for i in range(9):
                x=-4.1+i*1.02
                if z<0 and abs(x)<1.4:continue
                mesh.box((x,.6,z),(.76,.44,.1),(.49+.025*(i%3),.42,.32,1))
        for y in (4.7,5.7,6.7,7.7):mesh.box((3,y,.23),(1.4,.07,.07),WOOD)
    # Bake gentle bottom/contact and vertical brush variation in the shared
    # mesh once; there is no per-house update or shader/texture allocation.
    for offset in range(0,len(mesh.vertices),40):
        x,y,z,nx,ny,nz,r,g,b,a=struct.unpack_from('<10f',mesh.vertices,offset)
        contact=.80+.20*min(1,max(0,y/2.1))
        wash=.97+.035*math.sin(x*1.7+z*.8+y*1.2)
        struct.pack_into('<4f',mesh.vertices,offset+24,r*contact*wash,g*contact*wash,b*contact*wash,a)
