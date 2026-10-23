"""Shared painted-image material mapping for the game and Blender exporter."""
import json
from functools import lru_cache
from pathlib import Path
NAMES = ('grass', 'soil', 'stone', 'sandstone', 'plaster', 'wood', 'roof',
         'moss', 'bark', 'leaf', 'cloth', 'leather', 'metal', 'snow', 'water', 'skin')
SIZES = (12., 9., 7., 12., 5., 3.2, 5.4, 8., 4., 5., 2., 2., 3., 12., 18., 2.)
# One palette drives GLB UVs, Blender UVs and the generated native shader.
# Broad painted forms need room; fabric/skin should never read as woven noise.
DETAIL_STRENGTH = (.55, .65, .7, .8, .35, .85, .9, .75,
                   .85, .8, .35, .5, .65, .6, .45, .2)
# Keep the existing restoration key: changing it would stack old GLB wrappers.
MARKER = 'gg_painted_clay_v3'

@lru_cache(maxsize=1)
def crew_palettes():
    path=Path(__file__).resolve().parents[1]/'qml/assets/authored/world/textures/clay-v4/crew-palettes.json'
    return json.loads(path.read_text()) if path.exists() else {}

def crew_family(name,c):
    for identity,rows in crew_palettes().items():
        if identity in name:
            row=min(rows,key=lambda row:sum((a-b)**2 for a,b in zip(c[:3],row['color'])))
            return True,row['family']
    return False,None

def color_family(c, mode='architecture'):
    r,g,b=c[:3]
    if mode=='character':
        if max(c[:3])<.035 or min(c[:3])>.88:return None
        if g>.42:return 15
        if b>r*1.25 or (g>r*1.35 and b>g*.7):return 10
        if r<.18 and g<.18 and b<.18:return 11
        if max(c[:3])-min(c[:3])<.07:return 12
        return 15
    if mode=='flora':
        if b>g*1.2 or (r>g*1.25 and r>.6):return 15
        if g>r*.98 and g>b*1.3:return 9
        if r>g*1.1 and r>b*1.15:return 8
        return 7
    if mode=='terrain':
        if min(c[:3])>.68:return 13
        if g>r*1.12:return 0
        if b>r*1.15:return 14
        if r>g*1.3 and g>b*1.2:return 1
        return 3 if r>g*1.15 else 7
    if g>r*1.08 and g>b*1.12:return 9
    if b>r*1.15 or (g>r*1.25 and b>g*.7):return 15 if g<.3 else 6
    if r>g*2.4:return 6
    if r>g*1.65:return 5
    if r>g*1.18 and g>b*1.4:return 4
    return 2

def family_for(name, c, mode='architecture'):
    name=name.lower().replace('sandover','')
    if mode=='character' and 'palette' in name:
        found,family=crew_family(name,c)
        if found:return family
    unpainted=('pupil','sclera','eye','glow','glass','window','beak')
    if mode!='flora':unpainted+=('iris',)
    if any(s in name for s in unpainted):return None
    if 'planet' in name or 'ashbell painted ground' in name:
        if 'snow' in name:return 13
        if 'sea_' in name:return 1 # seabed, not the visible animated water plane
        if 'beach' in name:return 1
        if 'rock' in name:return 7
        if 'volcanic' in name:return 3
        return 0
    groups=((8,('bark','trunk','root')), (9,('leaf','canopy','frond','needles','fern')),
            (0,('grass','meadow')), (7,('moss rock','boulder','lichen')),
            (3,('sandstone',)), (2,('stone','rock','foundation')),
            (4,('plaster','limewash','wall')), (6,('roof','terracotta','thatch','tile')),
            (5,('wood','timber','plank','beam','door','crate','board','piling')),
            (10,('cloth','canvas','sail','fabric')), (11,('leather','boot','belt','hair','brow')),
            (12,('iron','steel','metal','copper','gold','blade','saber')),
            (14,('water','sea')), (13,('snow','cloud')),
            (1,('sand','soil','dirt','mud')), (15,('skin','goblin','belly','fur','feather','fish','petal')))
    # Palette materials encode multiple surfaces with COLOR_0 instead of slots.
    if 'palette' in name or name in ('gg_world_clay_r1','gg_landscape_clay'):return color_family(c,mode)
    for i,words in groups:
        if any(w in name for w in words):return i
    return color_family(c,mode)

def project(p,n,tile):
    ax,ay,az=map(abs,n)
    if ay>=ax and ay>=az:u,v=p[0],p[2]
    elif ax>=az:u,v=p[2],p[1]
    else:u,v=p[0],p[1]
    if tile==SIZES[6] and ay>.3:u,v=p[2],-abs(p[0])
    return u/tile,v/tile
