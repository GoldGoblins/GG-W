"""Original camera down-ray: authored faces, portal holes, terrain, DETAIL retry."""
import math
from backend.game_engine_adapter_portals import dot

def polygon_contains(points,plane,point):
    axes=[i for i in range(3) if i!=max(range(3),key=lambda k:abs(plane[k]))];u,v=axes;inside=False
    for i,a in enumerate(points):
        b=points[(i+1)%len(points)];dx,dy=b[u]-a[u],b[v]-a[v];px,py=point[u]-a[u],point[v]-a[v]
        if abs(dx*py-dy*px)<1e-7 and min(a[u],b[u])-1e-7<=point[u]<=max(a[u],b[u])+1e-7 and min(a[v],b[v])-1e-7<=point[v]<=max(a[v],b[v])+1e-7:return True
        if (a[v]>point[v])!=(b[v]>point[v]) and point[u]<(b[u]-a[u])*(point[v]-a[v])/(b[v]-a[v])+a[u]:inside=not inside
    return inside

def camera_seeds(page,eye,terrain=None):
    groups=page.metadata['groups'];portals=page.metadata.get('portals') or {};refs=portals.get('refs',[]);infos=portals.get('infos',[])
    height,row=page.surface.down_ray(*eye,props=False);best=row.get('group') if row else None;across=None
    best_y=height if height is not None else -math.inf
    def column(group):
        corners=group.get('corners')
        return not corners or min(p[0] for p in corners)<=eye[0]<=max(p[0] for p in corners) and min(p[2] for p in corners)<=eye[2]<=max(p[2] for p in corners) and min(p[1] for p in corners)<=eye[1]
    for gi,group in enumerate(groups):
        if not column(group):continue
        for ref in refs[group['portal_start']:group['portal_start']+group['portal_count']]:
            if not 0<=ref['portal']<len(infos):continue
            info=infos[ref['portal']];nx,ny,nz,d=info['plane'];distance=dot(info['plane'][:3],eye)+d
            if abs(ny)<1e-4:
                if abs(distance)>.1:continue
                y=eye[1]
            else:
                y=-(nx*eye[0]+nz*eye[2]+d)/ny
                if y>eye[1]:continue
            if y<best_y-1e-4 or not polygon_contains(info['points'],info['plane'],(eye[0],y,eye[2])):continue
            chosen=gi if (distance>=0)==(ref['side']>0) else ref['group']
            if not 0<=chosen<len(groups):continue
            other=ref['group'] if chosen==gi else gi
            best,best_y=chosen,y;across=other if 0<=other<len(groups) and other!=chosen else None
    if best is None and (terrain is None or terrain>eye[1]) and page.camera_only is not None:
        height,row=page.camera_only.down_ray(*eye,props=False);best=row.get('group') if row else None;best_y=height if height is not None else -math.inf
    if best is None or eye[1]-best_y>1760 or groups[best]['flags']&8 or terrain is not None and best_y<terrain<=eye[1]:return None,()
    return best,tuple(g for g in (best,across) if g is not None)
